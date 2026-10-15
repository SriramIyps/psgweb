-- =====================================================================
-- PSG CAS CONNECT — Migration 05: VP to HR Department Forwarding Rules & RPCs
-- Always runs after 04_forward_migration.sql
-- =====================================================================

-- 1. ADD VP FORWARD TRACKING COLUMNS TO APPLICATIONS TABLE
ALTER TABLE public.applications
    ADD COLUMN IF NOT EXISTS vp_forwarded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS vp_forwarded_by TEXT;

-- 2. VP DEPARTMENT FORWARD TO HR RPC
CREATE OR REPLACE FUNCTION public.rpc_vp_forward_to_hr(
    p_department TEXT,
    p_who TEXT
) RETURNS VOID AS $$
DECLARE
    v_eligible_count INTEGER;
    v_already_forwarded INTEGER;
    v_pending_count INTEGER;
BEGIN
    -- 1. Lock HOD-forwarded Eligible applications for the department
    PERFORM id FROM public.applications 
    WHERE department = p_department 
      AND is_locked = true 
      AND hod_forwarded_at IS NOT NULL 
      AND hod_status = 'Eligible'
    FOR UPDATE;

    -- 2. Check candidate count
    SELECT COUNT(*) INTO v_eligible_count
    FROM public.applications
    WHERE department = p_department 
      AND is_locked = true 
      AND hod_forwarded_at IS NOT NULL 
      AND hod_status = 'Eligible';

    IF v_eligible_count = 0 THEN
        RAISE EXCEPTION 'CONNECT_RULE: No HOD-forwarded eligible candidates found for department "%"', p_department;
    END IF;

    -- 3. Check if department has already been forwarded to HR
    SELECT COUNT(*) INTO v_already_forwarded
    FROM public.applications
    WHERE department = p_department 
      AND is_locked = true 
      AND hod_forwarded_at IS NOT NULL 
      AND hod_status = 'Eligible'
      AND vp_forwarded_at IS NOT NULL;

    IF v_already_forwarded > 0 THEN
        RAISE EXCEPTION 'CONNECT_RULE: Department "%" has already been forwarded to HR', p_department;
    END IF;

    -- 4. Check for unscrutinised / pending VP applications
    SELECT COUNT(*) INTO v_pending_count
    FROM public.applications
    WHERE department = p_department 
      AND is_locked = true 
      AND hod_forwarded_at IS NOT NULL 
      AND hod_status = 'Eligible'
      AND (vp_status IS NULL OR COALESCE(vp_status, 'Pending') = 'Pending');

    IF v_pending_count > 0 THEN
        RAISE EXCEPTION 'CONNECT_RULE: Cannot forward department "%" to HR: % candidates still pending VP decision', p_department, v_pending_count;
    END IF;

    -- 5. Perform forward update on ALL HOD-forwarded Eligible rows for the department
    UPDATE public.applications
    SET vp_forwarded_at = NOW(),
        vp_forwarded_by = p_who
    WHERE department = p_department 
      AND is_locked = true 
      AND hod_forwarded_at IS NOT NULL 
      AND hod_status = 'Eligible';

    -- 6. Audit Log Entry
    INSERT INTO public.audit_log (who, action, application_id, old_value, new_value, when_timestamp)
    VALUES (p_who, 'VP_FORWARD_DEPARTMENT_TO_HR', NULL, p_department, NOW()::text, NOW());
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

REVOKE ALL ON FUNCTION public.rpc_vp_forward_to_hr(TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_vp_forward_to_hr(TEXT, TEXT) TO service_role;

-- 3. REWRITE VP REVIEW RPC (Locks VP modifications after department forwarding to HR)
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
    v_vp_forwarded_at TIMESTAMPTZ;
BEGIN
    -- 1. Select & Lock application
    SELECT hod_status, vp_status, hod_forwarded_at, vp_forwarded_at
    INTO v_hod_status, v_old_vp_status, v_hod_forwarded_at, v_vp_forwarded_at
    FROM public.applications
    WHERE id = p_app_id FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CONNECT_RULE: Application with ID % not found', p_app_id;
    END IF;

    -- Rejects if department has not been forwarded by HOD
    IF v_hod_forwarded_at IS NULL THEN
        RAISE EXCEPTION 'CONNECT_RULE: Cannot perform VP review: department has not been forwarded by HOD';
    END IF;

    -- Rejects if department has already been forwarded to HR
    IF v_vp_forwarded_at IS NOT NULL THEN
        RAISE EXCEPTION 'CONNECT_RULE: Cannot modify VP decision after department has been forwarded to HR';
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
