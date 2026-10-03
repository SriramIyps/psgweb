-- =====================================================================
-- PSG CAS CONNECT — SQL Test Suite: Department Forwarding Rules Verification
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
    v_draft_id BIGINT;
BEGIN
    -- Setup close_date in the past
    INSERT INTO public.app_settings (key, value)
        VALUES ('close_date', '2020-01-01')
    ON CONFLICT (key) DO UPDATE SET value = '2020-01-01';

    -- Insert 2 submitted applications and 1 draft application for department 'ZZFORWARD'
    INSERT INTO public.applications
        (app_uuid, department, name, email, mobile_no, position, hod_status, vp_status, is_locked)
    VALUES
        ('ZZFWD/T1', 'ZZFORWARD', 'Cand 1', 'c1@zz.ac.in', '9999999901', 'Assistant Professor', NULL, NULL, true)
    RETURNING id INTO v_app_id1;

    INSERT INTO public.applications
        (app_uuid, department, name, email, mobile_no, position, hod_status, vp_status, is_locked)
    VALUES
        ('ZZFWD/T2', 'ZZFORWARD', 'Cand 2', 'c2@zz.ac.in', '9999999902', 'Assistant Professor', NULL, NULL, true)
    RETURNING id INTO v_app_id2;

    INSERT INTO public.applications
        (app_uuid, department, name, email, mobile_no, position, hod_status, vp_status, is_locked)
    VALUES
        ('ZZFWD/DRAFT', 'ZZFORWARD', 'Draft Cand', 'draft@zz.ac.in', '9999999903', 'Assistant Professor', NULL, NULL, false)
    RETURNING id INTO v_draft_id;

    -- Test 1: Forwarding before close_date is rejected
    BEGIN
        UPDATE public.app_settings SET value = '2099-12-31' WHERE key = 'close_date';
        PERFORM public.rpc_hod_forward_department('ZZFORWARD', 'hod@zzforward.ac.in');
        INSERT INTO test_results VALUES (1, 'Forwarding before close_date is rejected', 'FAIL', 'No exception');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES (1, 'Forwarding before close_date is rejected', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES (1, 'Forwarding before close_date is rejected', 'FAIL', SQLERRM);
        END IF;
    END;

    UPDATE public.app_settings SET value = '2020-01-01' WHERE key = 'close_date';

    -- Test 2: Forwarding rejected when submitted apps are pending HOD scrutiny
    BEGIN
        PERFORM public.rpc_hod_forward_department('ZZFORWARD', 'hod@zzforward.ac.in');
        INSERT INTO test_results VALUES (2, 'Forwarding rejected when pending apps exist', 'FAIL', 'No exception');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES (2, 'Forwarding rejected when pending apps exist', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES (2, 'Forwarding rejected when pending apps exist', 'FAIL', SQLERRM);
        END IF;
    END;

    -- Scrutinize app 1 as Eligible, app 2 as Not Eligible
    PERFORM public.rpc_update_hod_status(v_app_id1, 'hod@zzforward.ac.in', 'ZZFORWARD', 'Eligible', 'Qualified');
    PERFORM public.rpc_update_hod_status(v_app_id2, 'hod@zzforward.ac.in', 'ZZFORWARD', 'Not Eligible', 'Lacks experience');

    -- Test 3: Forwarding succeeds even when draft application exists (drafts never block)
    BEGIN
        PERFORM public.rpc_hod_forward_department('ZZFORWARD', 'hod@zzforward.ac.in');
        INSERT INTO test_results VALUES (3, 'Forwarding succeeds when submitted apps scrutinised (drafts ignored)', 'PASS', '');
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results VALUES (3, 'Forwarding succeeds when submitted apps scrutinised (drafts ignored)', 'FAIL', SQLERRM);
    END;

    -- Test 4: Re-forwarding already forwarded department is rejected
    BEGIN
        PERFORM public.rpc_hod_forward_department('ZZFORWARD', 'hod@zzforward.ac.in');
        INSERT INTO test_results VALUES (4, 'Re-forwarding already forwarded department rejected', 'FAIL', 'No exception');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES (4, 'Re-forwarding already forwarded department rejected', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES (4, 'Re-forwarding already forwarded department rejected', 'FAIL', SQLERRM);
        END IF;
    END;

    -- Test 5: HOD modification rejected after forwarding
    BEGIN
        PERFORM public.rpc_update_hod_status(v_app_id1, 'hod@zzforward.ac.in', 'ZZFORWARD', 'Not Eligible', 'Changed mind');
        INSERT INTO test_results VALUES (5, 'HOD modification rejected after forwarding', 'FAIL', 'No exception');
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE '%CONNECT_RULE:%' THEN
            INSERT INTO test_results VALUES (5, 'HOD modification rejected after forwarding', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES (5, 'HOD modification rejected after forwarding', 'FAIL', SQLERRM);
        END IF;
    END;

    -- Test 6: Forwarding succeeds when ALL submitted apps are 'Not Eligible' and sets hod_forwarded_at on all rows
    DECLARE
        v_ne_id BIGINT;
        v_fwd_count INT;
    BEGIN
        INSERT INTO public.applications
            (app_uuid, department, name, email, mobile_no, position, hod_status, vp_status, is_locked)
        VALUES
            ('ZZFWD/NE1', 'ZZALLNOTELIG', 'Cand NE1', 'ne1@zz.ac.in', '9999999904', 'Assistant Professor', NULL, NULL, true)
        RETURNING id INTO v_ne_id;

        PERFORM public.rpc_update_hod_status(v_ne_id, 'hod@zzall.ac.in', 'ZZALLNOTELIG', 'Not Eligible', 'Does not meet UGC criteria');

        PERFORM public.rpc_hod_forward_department('ZZALLNOTELIG', 'hod@zzall.ac.in');

        SELECT COUNT(*) INTO v_fwd_count
        FROM public.applications
        WHERE department = 'ZZALLNOTELIG' AND hod_forwarded_at IS NOT NULL;

        IF v_fwd_count = 1 THEN
            INSERT INTO test_results VALUES (6, 'All Not Eligible department successfully forwarded & locked', 'PASS', '');
        ELSE
            INSERT INTO test_results VALUES (6, 'All Not Eligible department successfully forwarded & locked', 'FAIL', 'Expected 1 forwarded row, got ' || v_fwd_count);
        END IF;
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results VALUES (6, 'All Not Eligible department successfully forwarded & locked', 'FAIL', SQLERRM);
    END;

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
