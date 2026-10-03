-- =====================================================================
-- PSG CAS CONNECT — Migration 04: Department Forwarding Rules & RPCs
-- Always runs after 03_audit_and_counters_migration.sql
-- =====================================================================

-- 1. ADD FORWARD TRACKING COLUMNS TO APPLICATIONS TABLE
ALTER TABLE public.applications
    ADD COLUMN IF NOT EXISTS hod_forwarded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS hod_forwarded_by TEXT;

-- 2. HOD DEPARTMENT FORWARD RPC
CREATE OR REPLACE FUNCTION public.rpc_hod_forward_department(
    p_department TEXT,
    p_who TEXT
) RETURNS VOID AS $$
DECLARE
    v_close_str TEXT;
    v_close_end TIMESTAMPTZ;
    v_submitted_count INTEGER;
    v_already_forwarded INTEGER;
    v_pending_count INTEGER;
BEGIN
    -- 1. Close Date Enforcement (Fail-closed)
    SELECT value INTO v_close_str FROM public.app_settings WHERE key = 'close_date';
    IF v_close_str IS NULL OR TRIM(v_close_str) = '' THEN
        RAISE EXCEPTION 'CONNECT_RULE: Application close date configuration is missing';
    END IF;

    BEGIN
        IF POSITION('T' IN v_close_str) > 0 THEN
            v_close_end := v_close_str::timestamptz;
        ELSE
            v_close_end := (SUBSTRING(v_close_str FROM 1 FOR 10) || ' 23:59:59.999999')::timestamp AT TIME ZONE 'Asia/Kolkata';
        END IF;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'CONNECT_RULE: Application close date configuration is invalid';
    END;

    IF NOW() <= v_close_end THEN
        RAISE EXCEPTION 'CONNECT_RULE: Department forwarding is not allowed before application close date';
    END IF;

    -- 2. Lock submitted applications for department
    PERFORM id FROM public.applications 
    WHERE department = p_department AND is_locked = true 
    FOR UPDATE;

    -- 3. Check submitted application count
    SELECT COUNT(*) INTO v_submitted_count
    FROM public.applications
    WHERE department = p_department AND is_locked = true;

    IF v_submitted_count = 0 THEN
        RAISE EXCEPTION 'CONNECT_RULE: No submitted applications found for department "%"', p_department;
    END IF;

    -- 4. Check if already forwarded
    SELECT COUNT(*) INTO v_already_forwarded
    FROM public.applications
    WHERE department = p_department AND is_locked = true AND hod_forwarded_at IS NOT NULL;

    IF v_already_forwarded > 0 THEN
        RAISE EXCEPTION 'CONNECT_RULE: Department "%" has already been forwarded to Vice Principal', p_department;
    END IF;

    -- 5. Check for unscrutinized / pending submitted applications
    SELECT COUNT(*) INTO v_pending_count
    FROM public.applications
    WHERE department = p_department 
      AND is_locked = true 
      AND (hod_status IS NULL OR COALESCE(hod_status, 'Pending') = 'Pending');

    IF v_pending_count > 0 THEN
        RAISE EXCEPTION 'CONNECT_RULE: Cannot forward department "%": % applications still pending HOD scrutiny', p_department, v_pending_count;
    END IF;

    -- 6. Perform forward update
    UPDATE public.applications
    SET hod_forwarded_at = NOW(),
        hod_forwarded_by = p_who
    WHERE department = p_department AND is_locked = true;

    -- 7. Audit Log Entry
    INSERT INTO public.audit_log (who, action, application_id, old_value, new_value, when_timestamp)
    VALUES (p_who, 'HOD_FORWARD_DEPARTMENT', NULL, p_department, NOW()::text, NOW());
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

REVOKE ALL ON FUNCTION public.rpc_hod_forward_department(TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_hod_forward_department(TEXT, TEXT) TO service_role;

-- 3. REWRITE HOD REVIEW RPC (Locks HOD modifications after forwarding)
CREATE OR REPLACE FUNCTION public.rpc_update_hod_status(
    p_app_id BIGINT,
    p_who TEXT,
    p_hod_department TEXT,
    p_status TEXT,
    p_remarks TEXT
) RETURNS VOID AS $$
DECLARE
    v_app_dept TEXT;
    v_old_hod_status TEXT;
    v_vp_status TEXT;
    v_hod_forwarded_at TIMESTAMPTZ;
    v_close_str TEXT;
    v_close_end TIMESTAMPTZ;
BEGIN
    -- 1. Select & Lock application
    SELECT department, hod_status, vp_status, hod_forwarded_at
    INTO v_app_dept, v_old_hod_status, v_vp_status, v_hod_forwarded_at
    FROM public.applications
    WHERE id = p_app_id FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CONNECT_RULE: Application with ID % not found', p_app_id;
    END IF;

    -- Lock HOD changes after department forwarding
    IF v_hod_forwarded_at IS NOT NULL THEN
        RAISE EXCEPTION 'CONNECT_RULE: Cannot modify HOD decision after department has been forwarded to Vice Principal';
    END IF;

    -- Treat NULL statuses as 'Pending'
    v_old_hod_status := COALESCE(v_old_hod_status, 'Pending');
    v_vp_status := COALESCE(v_vp_status, 'Pending');

    -- 2. Department Check
    IF p_hod_department IS NULL OR TRIM(p_hod_department) = '' OR v_app_dept IS NULL OR LOWER(TRIM(p_hod_department)) != LOWER(TRIM(v_app_dept)) THEN
        RAISE EXCEPTION 'CONNECT_RULE: HOD department "%" does not match application department "%"', COALESCE(p_hod_department, ''), COALESCE(v_app_dept, '');
    END IF;

    -- 3. Close Date Enforcement (Fail-closed)
    SELECT value INTO v_close_str FROM public.app_settings WHERE key = 'close_date';
    IF v_close_str IS NULL OR TRIM(v_close_str) = '' THEN
        RAISE EXCEPTION 'CONNECT_RULE: Application close date configuration is missing';
    END IF;

    BEGIN
        IF POSITION('T' IN v_close_str) > 0 THEN
            v_close_end := v_close_str::timestamptz;
        ELSE
            v_close_end := (SUBSTRING(v_close_str FROM 1 FOR 10) || ' 23:59:59.999999')::timestamp AT TIME ZONE 'Asia/Kolkata';
        END IF;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'CONNECT_RULE: Application close date configuration is invalid';
    END;

    IF NOW() <= v_close_end THEN
        RAISE EXCEPTION 'CONNECT_RULE: HOD review is not allowed before application close date';
    END IF;

    -- 4. Status Validation & Business Rules
    IF p_status NOT IN ('Eligible', 'Not Eligible') THEN
        RAISE EXCEPTION 'CONNECT_RULE: Invalid HOD status "%"; must be Eligible or Not Eligible', p_status;
    END IF;

    IF v_vp_status != 'Pending' THEN
        RAISE EXCEPTION 'CONNECT_RULE: Cannot modify HOD decision after VP review has been completed';
    END IF;

    IF p_status = 'Not Eligible' AND (p_remarks IS NULL OR TRIM(p_remarks) = '') THEN
        RAISE EXCEPTION 'CONNECT_RULE: Remarks/reason is mandatory when marking a candidate Not Eligible';
    END IF;

    -- 5. Update Application
    UPDATE public.applications
    SET hod_status = p_status,
        hod_remarks = p_remarks,
        hod_reviewed_at = NOW(),
        hod_reviewer = p_who
    WHERE id = p_app_id;

    -- 6. Audit Log Entry
    INSERT INTO public.audit_log (who, action, application_id, old_value, new_value, when_timestamp)
    VALUES (p_who, 'HOD_REVIEW_UPDATE', p_app_id, v_old_hod_status, p_status, NOW());
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

REVOKE ALL ON FUNCTION public.rpc_update_hod_status(BIGINT, TEXT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_update_hod_status(BIGINT, TEXT, TEXT, TEXT, TEXT) TO service_role;

-- 4. REWRITE VP REVIEW RPC (Rejects if department is not forwarded)
CREATE OR REPLACE FUNCTION public.rpc_update_vp_status(
    p_app_id BIGINT,
    p_who TEXT,
    p_status TEXT,
    p_remarks TEXT
) RETURNS VOID AS $$
DECLARE
    v_hod_status TEXT;
    v_old_vp_status TEXT;
    v_hod_forwarded_at TIMESTAMPTZ;
BEGIN
    -- 1. Select & Lock application
    SELECT hod_status, vp_status, hod_forwarded_at
    INTO v_hod_status, v_old_vp_status, v_hod_forwarded_at
    FROM public.applications
    WHERE id = p_app_id FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CONNECT_RULE: Application with ID % not found', p_app_id;
    END IF;

    -- Rejects if department has not been forwarded by HOD
    IF v_hod_forwarded_at IS NULL THEN
        RAISE EXCEPTION 'CONNECT_RULE: Cannot perform VP review: department has not been forwarded by HOD';
    END IF;

    -- Treat NULL statuses as 'Pending'
    v_hod_status := COALESCE(v_hod_status, 'Pending');
    v_old_vp_status := COALESCE(v_old_vp_status, 'Pending');

    -- 2. Status Validation & Business Rules
    IF p_status NOT IN ('Shortlisted', 'Not Shortlisted') THEN
        RAISE EXCEPTION 'CONNECT_RULE: Invalid VP status "%"; must be Shortlisted or Not Shortlisted', p_status;
    END IF;

    IF v_hod_status != 'Eligible' THEN
        RAISE EXCEPTION 'CONNECT_RULE: Cannot shortlist: candidate has not been marked Eligible by HOD';
    END IF;

    IF p_status = 'Not Shortlisted' AND (p_remarks IS NULL OR TRIM(p_remarks) = '') THEN
        RAISE EXCEPTION 'CONNECT_RULE: Remarks/reason is mandatory when marking a candidate Not Shortlisted';
    END IF;

    -- 3. Update Application
    UPDATE public.applications
    SET vp_status = p_status,
        vp_remarks = p_remarks,
        vp_reviewed_at = NOW(),
        vp_reviewer = p_who
    WHERE id = p_app_id;

    -- 4. Audit Log Entry
    INSERT INTO public.audit_log (who, action, application_id, old_value, new_value, when_timestamp)
    VALUES (p_who, 'VP_REVIEW_UPDATE', p_app_id, v_old_vp_status, p_status, NOW());
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

REVOKE ALL ON FUNCTION public.rpc_update_vp_status(BIGINT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_update_vp_status(BIGINT, TEXT, TEXT, TEXT) TO service_role;
