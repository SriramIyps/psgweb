-- =====================================================================
-- PSG CAS CONNECT — Rollback Script for Migration 02
-- Run this if you need to safely revert Migration 02.
-- =====================================================================

DROP FUNCTION IF EXISTS public.save_application_research(BIGINT, JSONB, JSONB, JSONB, JSONB, BOOLEAN, TEXT, TEXT, JSONB);

DROP TABLE IF EXISTS public.app_publications CASCADE;
DROP TABLE IF EXISTS public.app_patents CASCADE;
DROP TABLE IF EXISTS public.app_consultancy CASCADE;
DROP TABLE IF EXISTS public.app_projects CASCADE;

ALTER TABLE public.applications DROP COLUMN IF EXISTS iso_involvement;
ALTER TABLE public.applications DROP COLUMN IF EXISTS iso_details;
ALTER TABLE public.applications DROP COLUMN IF EXISTS naac_iqac_details;
ALTER TABLE public.applications DROP COLUMN IF EXISTS admin_positions_json;
