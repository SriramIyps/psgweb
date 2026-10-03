-- =====================================================================
-- PSG CAS CONNECT — SQL Test Suite: Review Rules Verification
-- Paste into Supabase SQL Editor.  Results appear as a grid.
-- The transaction is rolled back at the end — no data is left behind.
--
-- Verify cleanup after running:
--   SELECT count(*) FROM public.applications WHERE department = 'ZZTEST';
--   -- must return 0
-- =====================================================================

BEGIN;

-- Temp table lives for this transaction only (ON COMMIT DROP).
-- The SELECT below is sent to the client BEFORE the ROLLBACK executes,
-- so the editor shows the full result grid even though the tx is rolled back.
CREATE TEMP TABLE test_results (
    test_no   INT,
    test_name TEXT,
    result    TEXT,
    detail    TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    v_app_id              BIGINT;
    v_audit_count         INT;
    v_initial_audit_count INT;
BEGIN
    -- ── Setup ────────────────────────────────────────────────────────
    -- Put close_date in the past so the "still open" check fires.
    INSERT INTO public.app_settings (key, value)
        VALUES ('close_date', '2020-01-01')
    ON CONFLICT (key) DO UPDATE SET value = '2020-01-01';

    INSERT INTO public.applications
        (app_uuid,     department, name,            email,                mobile_no,    position,             hod_status, vp_status, is_locked)
    VALUES
        ('ZZTEST/T1', 'ZZTEST',   'Test Candidate','zztest@example.com', '9999999999', 'Assistant Professor', NULL,       NULL,      true)
    RETURNING id INTO v_app_id;

    SELECT COUNT(*) INTO v_initial_audit_count
    FROM public.audit_log WHERE application_id = v_app_id;

    -- ── Test 1: HOD review while portal is still OPEN is rejected ───
    -- Advance close_date into the future so the RPC thinks the portal is open.
    BEGIN
        UPDATE public.app_settings SET value = '2099-12-31' WHERE key = 'close_date';
        PERFORM public.rpc_update_hod_status(
            v_app_id, 'hod@zztest.ac.in', 'ZZTEST', 'Eligible', 'Good candidate');
        INSERT INTO test_results VALUES
            (1, 'HOD review rejected while portal still open', 'FAIL', 'No exception raised');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES
                (1, 'HOD review rejected while portal still open', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES
                (1, 'HOD review rejected while portal still open', 'FAIL',
                 'Unexpected error: ' || SQLERRM);
        END IF;
    END;

    -- Restore close_date to the past for all remaining tests.
    UPDATE public.app_settings SET value = '2020-01-01' WHERE key = 'close_date';

    -- ── Test 2: HOD review of wrong department is rejected ──────────
    BEGIN
        PERFORM public.rpc_update_hod_status(
            v_app_id, 'hod@other.ac.in', 'OTHER_DEPT', 'Eligible', 'Good candidate');
        INSERT INTO test_results VALUES
            (2, 'HOD review of wrong department is rejected', 'FAIL', 'No exception raised');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES
                (2, 'HOD review of wrong department is rejected', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES
                (2, 'HOD review of wrong department is rejected', 'FAIL',
                 'Unexpected error: ' || SQLERRM);
        END IF;
    END;

    -- ── Test 3: "Not Eligible" without a reason is rejected ─────────
    BEGIN
        PERFORM public.rpc_update_hod_status(
            v_app_id, 'hod@zztest.ac.in', 'ZZTEST', 'Not Eligible', '');
        INSERT INTO test_results VALUES
            (3, '"Not Eligible" without a reason is rejected', 'FAIL', 'No exception raised');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES
                (3, '"Not Eligible" without a reason is rejected', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES
                (3, '"Not Eligible" without a reason is rejected', 'FAIL',
                 'Unexpected error: ' || SQLERRM);
        END IF;
    END;

    -- ── Test 4: Unknown application id is rejected ──────────────────
    BEGIN
        PERFORM public.rpc_update_hod_status(
            9999999, 'hod@zztest.ac.in', 'ZZTEST', 'Eligible', 'Good');
        INSERT INTO test_results VALUES
            (4, 'Unknown application id is rejected', 'FAIL', 'No exception raised');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES
                (4, 'Unknown application id is rejected', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES
                (4, 'Unknown application id is rejected', 'FAIL',
                 'Unexpected error: ' || SQLERRM);
        END IF;
    END;

    -- ── Test 5: VP cannot act before HOD marks Eligible ─────────────
    BEGIN
        PERFORM public.rpc_update_vp_status(
            v_app_id, 'vp@psgcas.ac.in', 'Shortlisted', 'Approved');
        INSERT INTO test_results VALUES
            (5, 'VP cannot act before HOD marks Eligible', 'FAIL', 'No exception raised');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES
                (5, 'VP cannot act before HOD marks Eligible', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES
                (5, 'VP cannot act before HOD marks Eligible', 'FAIL',
                 'Unexpected error: ' || SQLERRM);
        END IF;
    END;

    -- ── Test 6: NULL hod_status application can be reviewed ─────────
    BEGIN
        PERFORM public.rpc_update_hod_status(
            v_app_id, 'hod@zztest.ac.in', 'ZZTEST', 'Eligible', 'Initial approval');
        INSERT INTO test_results VALUES
            (6, 'NULL hod_status application can be reviewed', 'PASS', '');
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results VALUES
            (6, 'NULL hod_status application can be reviewed', 'FAIL', SQLERRM);
    END;

    -- ── Test 7: HOD can change decision before VP acts ──────────────
    BEGIN
        PERFORM public.rpc_update_hod_status(
            v_app_id, 'hod@zztest.ac.in', 'ZZTEST', 'Not Eligible', 'Revised decision');
        INSERT INTO test_results VALUES
            (7, 'HOD can change decision before VP acts', 'PASS', '');
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results VALUES
            (7, 'HOD can change decision before VP acts', 'FAIL', SQLERRM);
    END;

    -- Reset to Eligible so VP tests can proceed.
    PERFORM public.rpc_update_hod_status(
        v_app_id, 'hod@zztest.ac.in', 'ZZTEST', 'Eligible', 'Restored to eligible');

    -- Forward department to VP before VP reviews
    PERFORM public.rpc_hod_forward_department('ZZTEST', 'hod@zztest.ac.in');

    -- ── Test 8: VP can shortlist after HOD marks Eligible ───────────
    BEGIN
        PERFORM public.rpc_update_vp_status(
            v_app_id, 'vp@psgcas.ac.in', 'Shortlisted', 'Shortlisted for interview');
        INSERT INTO test_results VALUES
            (8, 'VP can shortlist after HOD marks Eligible', 'PASS', '');
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results VALUES
            (8, 'VP can shortlist after HOD marks Eligible', 'FAIL', SQLERRM);
    END;

    -- ── Test 9: HOD cannot change after VP has acted ─────────────────
    BEGIN
        PERFORM public.rpc_update_hod_status(
            v_app_id, 'hod@zztest.ac.in', 'ZZTEST', 'Not Eligible', 'Attempt after VP');
        INSERT INTO test_results VALUES
            (9, 'HOD cannot change after VP has acted', 'FAIL', 'No exception raised');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES
                (9, 'HOD cannot change after VP has acted', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES
                (9, 'HOD cannot change after VP has acted', 'FAIL',
                 'Unexpected error: ' || SQLERRM);
        END IF;
    END;

    -- ── Test 10: Audit log row count ─────────────────────────────────
    -- Successful writes on v_app_id:
    --   Test 6  → HOD Eligible           (+1)
    --   Test 7  → HOD Not Eligible       (+1)
    --   Restore → HOD Eligible           (+1)
    --   Test 8  → VP Shortlisted         (+1)
    -- Total expected = 4
    SELECT COUNT(*) INTO v_audit_count
    FROM public.audit_log WHERE application_id = v_app_id;

    IF v_audit_count = 4 THEN
        INSERT INTO test_results VALUES
            (10, 'Audit log: 4 rows for 4 successful changes', 'PASS',
             'count = ' || v_audit_count);
    ELSE
        INSERT INTO test_results VALUES
            (10, 'Audit log: 4 rows for 4 successful changes', 'FAIL',
             'expected 4, got ' || v_audit_count);
    END IF;

END $$;

-- ── Summary row (test_no = 0 → sorts to the top) ────────────────────
INSERT INTO test_results (test_no, test_name, result, detail)
SELECT
    0,
    '*** SUMMARY ***',
    format('%s PASS  /  %s FAIL',
        COUNT(*) FILTER (WHERE result = 'PASS'),
        COUNT(*) FILTER (WHERE result = 'FAIL')),
    'out of ' || COUNT(*) || ' tests'
FROM test_results;

-- The editor receives this result set before the ROLLBACK fires.
SELECT * FROM test_results ORDER BY test_no;

ROLLBACK;
-- Every INSERT above (applications, app_settings update, audit_log) is rolled back.
-- The temp table is dropped (ON COMMIT DROP).
--
-- Confirm nothing leaked:
--   SELECT count(*) FROM public.applications WHERE department = 'ZZTEST';  -- must return 0
