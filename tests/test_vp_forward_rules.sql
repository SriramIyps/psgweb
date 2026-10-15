-- =====================================================================
-- PSG CAS CONNECT — SQL Test Suite: VP to HR Forwarding Rules Verification
-- Paste into Supabase SQL Editor. Results appear as a grid.
-- The transaction is rolled back at the end — no data is left behind.
-- =====================================================================

BEGIN;

CREATE TEMP TABLE test_results (
    test_no   INT,
    test_name TEXT,
    result    TEXT,
    detail    TEXT
) ON COMMIT DROP;

DO $$
DECLARE
    v_app_id1 BIGINT;
    v_app_id2 BIGINT;
    v_ne_id BIGINT;
    v_fwd_count INT;
    v_audit_count INT;
BEGIN
    -- Setup close_date in the past
    INSERT INTO public.app_settings (key, value)
        VALUES ('close_date', '2020-01-01')
    ON CONFLICT (key) DO UPDATE SET value = '2020-01-01';

    -- Insert 2 HOD-forwarded Eligible applications for department 'ZZVPFWD'
    INSERT INTO public.applications
        (app_uuid, department, name, email, mobile_no, position, hod_status, vp_status, is_locked, hod_forwarded_at, hod_forwarded_by)
    VALUES
        ('ZZVP/T1', 'ZZVPFWD', 'VP Cand 1', 'v1@zz.ac.in', '9998887701', 'Assistant Professor', 'Eligible', NULL, true, NOW(), 'hod@zz.ac.in')
    RETURNING id INTO v_app_id1;

    INSERT INTO public.applications
        (app_uuid, department, name, email, mobile_no, position, hod_status, vp_status, is_locked, hod_forwarded_at, hod_forwarded_by)
    VALUES
        ('ZZVP/T2', 'ZZVPFWD', 'VP Cand 2', 'v2@zz.ac.in', '9998887702', 'Assistant Professor', 'Eligible', NULL, true, NOW(), 'hod@zz.ac.in')
    RETURNING id INTO v_app_id2;

    -- Test 1: Forward to HR rejected while candidates are still Pending VP decision
    BEGIN
        PERFORM public.rpc_vp_forward_to_hr('ZZVPFWD', 'vp@psgcas.ac.in');
        INSERT INTO test_results VALUES (1, 'Forward to HR rejected while candidates pending VP review', 'FAIL', 'No exception raised');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES (1, 'Forward to HR rejected while candidates pending VP review', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES (1, 'Forward to HR rejected while candidates pending VP review', 'FAIL', SQLERRM);
        END IF;
    END;

    -- VP scrutinizes app 1 as Shortlisted, app 2 as Not Shortlisted (with reason)
    PERFORM public.rpc_update_vp_status(v_app_id1, 'vp@psgcas.ac.in', 'Shortlisted', 'Strong credentials');
    PERFORM public.rpc_update_vp_status(v_app_id2, 'vp@psgcas.ac.in', 'Not Shortlisted', 'Insufficient publications');

    -- Test 2: Forward to HR succeeds when all candidates reviewed
    BEGIN
        PERFORM public.rpc_vp_forward_to_hr('ZZVPFWD', 'vp@psgcas.ac.in');
        INSERT INTO test_results VALUES (2, 'Forward to HR succeeds when all candidates reviewed', 'PASS', '');
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results VALUES (2, 'Forward to HR succeeds when all candidates reviewed', 'FAIL', SQLERRM);
    END;

    -- Test 3: Re-forwarding already forwarded department to HR rejected
    BEGIN
        PERFORM public.rpc_vp_forward_to_hr('ZZVPFWD', 'vp@psgcas.ac.in');
        INSERT INTO test_results VALUES (3, 'Re-forwarding department to HR rejected', 'FAIL', 'No exception raised');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES (3, 'Re-forwarding department to HR rejected', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES (3, 'Re-forwarding department to HR rejected', 'FAIL', SQLERRM);
        END IF;
    END;

    -- Test 4: VP status modification rejected after forwarding to HR
    BEGIN
        PERFORM public.rpc_update_vp_status(v_app_id1, 'vp@psgcas.ac.in', 'Not Shortlisted', 'Changed mind');
        INSERT INTO test_results VALUES (4, 'VP modification rejected after forwarding to HR', 'FAIL', 'No exception raised');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES (4, 'VP modification rejected after forwarding to HR', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES (4, 'VP modification rejected after forwarding to HR', 'FAIL', SQLERRM);
        END IF;
    END;

    -- Test 5: Forwarding succeeds when ALL candidates are 'Not Shortlisted' and stamps vp_forwarded_at on all rows
    BEGIN
        INSERT INTO public.applications
            (app_uuid, department, name, email, mobile_no, position, hod_status, vp_status, is_locked, hod_forwarded_at, hod_forwarded_by)
        VALUES
            ('ZZVP/NE1', 'ZZVPALLNOT', 'VP Cand NE', 'vpne@zz.ac.in', '9998887703', 'Assistant Professor', 'Eligible', NULL, true, NOW(), 'hod@zz.ac.in')
        RETURNING id INTO v_ne_id;

        PERFORM public.rpc_update_vp_status(v_ne_id, 'vp@psgcas.ac.in', 'Not Shortlisted', 'Did not meet requirements');

        PERFORM public.rpc_vp_forward_to_hr('ZZVPALLNOT', 'vp@psgcas.ac.in');

        SELECT COUNT(*) INTO v_fwd_count
        FROM public.applications
        WHERE department = 'ZZVPALLNOT' AND vp_forwarded_at IS NOT NULL;

        IF v_fwd_count = 1 THEN
            INSERT INTO test_results VALUES (5, 'All Not Shortlisted department successfully forwarded & locked', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES (5, 'All Not Shortlisted department successfully forwarded & locked', 'FAIL', 'Expected 1 forwarded row, got ' || v_fwd_count);
        END IF;
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results VALUES (5, 'All Not Shortlisted department successfully forwarded & locked', 'FAIL', SQLERRM);
    END;

    -- Test 6: Audit log row created for VP_FORWARD_DEPARTMENT_TO_HR
    SELECT COUNT(*) INTO v_audit_count
    FROM public.audit_log
    WHERE action = 'VP_FORWARD_DEPARTMENT_TO_HR' AND old_value = 'ZZVPFWD';

    IF v_audit_count >= 1 THEN
        INSERT INTO test_results VALUES (6, 'Audit log row created for VP_FORWARD_DEPARTMENT_TO_HR', 'PASS', 'count = ' || v_audit_count);
    ELSE
        INSERT INTO test_results VALUES (6, 'Audit log row created for VP_FORWARD_DEPARTMENT_TO_HR', 'FAIL', 'expected >= 1, got ' || v_audit_count);
    END IF;

END $$;

INSERT INTO test_results (test_no, test_name, result, detail)
SELECT
    0,
    '*** SUMMARY ***',
    format('%s PASS / %s FAIL',
        COUNT(*) FILTER (WHERE result = 'PASS'),
        COUNT(*) FILTER (WHERE result = 'FAIL')),
    'out of ' || COUNT(*) || ' tests'
FROM test_results;

SELECT * FROM test_results ORDER BY test_no;

ROLLBACK;
