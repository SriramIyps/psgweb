-- =====================================================================
-- PSG CAS CONNECT — RBAC Migration
-- Run this in your Supabase SQL Editor AFTER the original schema exists.
-- This adds: profiles table, status workflow columns, RLS policies.
-- =====================================================================

-- ─────────────────────────────────────────────
-- 1. PROFILES TABLE (linked to auth.users)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.profiles (
    id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email       TEXT UNIQUE NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('candidate','hod','superadmin','hr','admin')),
    department  TEXT,
    full_name   TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

-- Auto-create profile on signup (for candidates)
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, role, full_name)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'role', 'candidate'),
        COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1))
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Drop if exists, then create
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- ─────────────────────────────────────────────
-- 2. UPDATE APPLICATIONS TABLE
-- ─────────────────────────────────────────────
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS hod_status TEXT DEFAULT 'Pending';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS vp_status TEXT DEFAULT 'Pending';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS is_locked BOOLEAN DEFAULT false;

-- Add check constraints (safe with IF NOT EXISTS via DO block)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'applications_hod_status_check'
    ) THEN
        ALTER TABLE public.applications
            ADD CONSTRAINT applications_hod_status_check
            CHECK (hod_status IN ('Pending', 'Eligible', 'Not Eligible'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'applications_vp_status_check'
    ) THEN
        ALTER TABLE public.applications
            ADD CONSTRAINT applications_vp_status_check
            CHECK (vp_status IN ('Pending', 'Shortlisted', 'Not Shortlisted'));
    END IF;
END $$;


-- ─────────────────────────────────────────────
-- 3. APPLICATION SETTINGS TABLE (for ADMIN)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.app_settings (
    id          SERIAL PRIMARY KEY,
    key         TEXT UNIQUE NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.app_settings ENABLE ROW LEVEL SECURITY;

INSERT INTO public.app_settings (key, value) VALUES
    ('applications_open', 'true'),
    ('deadline_date', '2026-12-31'),
    ('announcement_text', 'Applications are open for the 2026-27 academic year.')
ON CONFLICT (key) DO NOTHING;


-- ─────────────────────────────────────────────
-- 4. DROP OLD WIDE-OPEN RLS POLICIES
-- ─────────────────────────────────────────────
DROP POLICY IF EXISTS "Public can submit applications" ON public.applications;
DROP POLICY IF EXISTS "Allow all access to applications" ON public.applications;
DROP POLICY IF EXISTS "Allow read access to staff" ON public.staff;


-- ─────────────────────────────────────────────
-- 5. PROFILES RLS POLICIES
-- ─────────────────────────────────────────────
DROP POLICY IF EXISTS "Users read own profile" ON public.profiles;
CREATE POLICY "Users read own profile" ON public.profiles
    FOR SELECT TO authenticated
    USING (auth.uid() = id);

DROP POLICY IF EXISTS "Admin reads all profiles" ON public.profiles;
CREATE POLICY "Admin reads all profiles" ON public.profiles
    FOR SELECT TO authenticated
    USING (
        EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
    );

DROP POLICY IF EXISTS "Admin manages profiles" ON public.profiles;
CREATE POLICY "Admin manages profiles" ON public.profiles
    FOR ALL TO authenticated
    USING (
        EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
    )
    WITH CHECK (
        EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
    );


-- ─────────────────────────────────────────────
-- 6. APPLICATIONS RLS POLICIES
-- ─────────────────────────────────────────────

-- 6a. Public (anon) can still submit applications
DROP POLICY IF EXISTS "Anon submit" ON public.applications;
CREATE POLICY "Anon submit" ON public.applications
    FOR INSERT TO anon
    WITH CHECK (true);

-- 6b. Candidate sees only own applications
DROP POLICY IF EXISTS "Candidate sees own apps" ON public.applications;
CREATE POLICY "Candidate sees own apps" ON public.applications
    FOR SELECT TO authenticated
    USING (
        user_id = auth.uid()
        AND EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'candidate')
    );

-- 6c. Candidate inserts own application
DROP POLICY IF EXISTS "Candidate inserts own app" ON public.applications;
CREATE POLICY "Candidate inserts own app" ON public.applications
    FOR INSERT TO authenticated
    WITH CHECK (
        user_id = auth.uid()
        AND EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'candidate')
    );

-- 6d. Candidate updates own app (only if not locked)
DROP POLICY IF EXISTS "Candidate updates own app" ON public.applications;
CREATE POLICY "Candidate updates own app" ON public.applications
    FOR UPDATE TO authenticated
    USING (
        user_id = auth.uid() AND is_locked = false
        AND EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'candidate')
    );

-- 6e. HOD sees applications for their department only
DROP POLICY IF EXISTS "HOD sees dept apps" ON public.applications;
CREATE POLICY "HOD sees dept apps" ON public.applications
    FOR SELECT TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles p
            WHERE p.id = auth.uid() AND p.role = 'hod' AND p.department = applications.department
        )
    );

-- 6f. HOD updates apps in their department
DROP POLICY IF EXISTS "HOD updates dept apps" ON public.applications;
CREATE POLICY "HOD updates dept apps" ON public.applications
    FOR UPDATE TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles p
            WHERE p.id = auth.uid() AND p.role = 'hod' AND p.department = applications.department
        )
    );

-- 6g. SUPERADMIN (VP) sees all applications
DROP POLICY IF EXISTS "VP sees all apps" ON public.applications;
CREATE POLICY "VP sees all apps" ON public.applications
    FOR SELECT TO authenticated
    USING (
        EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'superadmin')
    );

-- 6h. VP updates applications
DROP POLICY IF EXISTS "VP updates apps" ON public.applications;
CREATE POLICY "VP updates apps" ON public.applications
    FOR UPDATE TO authenticated
    USING (
        EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'superadmin')
    );

-- 6i. HR sees only Shortlisted candidates
DROP POLICY IF EXISTS "HR sees shortlisted" ON public.applications;
CREATE POLICY "HR sees shortlisted" ON public.applications
    FOR SELECT TO authenticated
    USING (
        vp_status = 'Shortlisted'
        AND EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'hr')
    );

-- 6j. Admin full access to applications
DROP POLICY IF EXISTS "Admin full access apps" ON public.applications;
CREATE POLICY "Admin full access apps" ON public.applications
    FOR ALL TO authenticated
    USING (
        EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
    )
    WITH CHECK (
        EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
    );


-- ─────────────────────────────────────────────
-- 7. APP_SETTINGS RLS POLICIES
-- ─────────────────────────────────────────────
DROP POLICY IF EXISTS "Anyone reads settings" ON public.app_settings;
CREATE POLICY "Anyone reads settings" ON public.app_settings
    FOR SELECT TO anon, authenticated
    USING (true);

DROP POLICY IF EXISTS "Admin manages settings" ON public.app_settings;
CREATE POLICY "Admin manages settings" ON public.app_settings
    FOR ALL TO authenticated
    USING (
        EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
    )
    WITH CHECK (
        EXISTS (SELECT 1 FROM public.profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
    );


-- ─────────────────────────────────────────────
-- 8. HELPER: function to get current user role
-- ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.get_my_role()
RETURNS TEXT AS $$
    SELECT role FROM public.profiles WHERE id = auth.uid();
$$ LANGUAGE sql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION public.get_my_department()
RETURNS TEXT AS $$
    SELECT department FROM public.profiles WHERE id = auth.uid();
$$ LANGUAGE sql SECURITY DEFINER STABLE;
