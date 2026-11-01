CREATE TABLE "course_passages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"source_id" uuid NOT NULL,
	"passage_key" text NOT NULL,
	"page" integer NOT NULL,
	"text" text NOT NULL
);
--> statement-breakpoint
CREATE TABLE "course_source_versions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"course_id" uuid NOT NULL,
	"document_id" text NOT NULL,
	"version" text NOT NULL,
	"title" text NOT NULL,
	"source" text NOT NULL,
	"digest" text NOT NULL
);
--> statement-breakpoint
CREATE TABLE "evidence_runs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"session_id" uuid NOT NULL,
	"request" jsonb NOT NULL,
	"manifest" jsonb NOT NULL,
	"model" text NOT NULL,
	"prompt_version" text NOT NULL,
	"status" text NOT NULL,
	"progress" jsonb NOT NULL,
	"stop_reason" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"deadline_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "assessment_session_sources" (
	"session_id" uuid NOT NULL,
	"source_id" uuid NOT NULL,
	CONSTRAINT "assessment_session_sources_session_id_source_id_pk" PRIMARY KEY("session_id","source_id")
);
--> statement-breakpoint
ALTER TABLE "course_passages" ADD CONSTRAINT "course_passages_source_id_course_source_versions_id_fk" FOREIGN KEY ("source_id") REFERENCES "public"."course_source_versions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "course_source_versions" ADD CONSTRAINT "course_source_versions_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "public"."courses"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_runs" ADD CONSTRAINT "evidence_runs_session_id_assessment_sessions_id_fk" FOREIGN KEY ("session_id") REFERENCES "public"."assessment_sessions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "assessment_session_sources" ADD CONSTRAINT "assessment_session_sources_session_id_assessment_sessions_id_fk" FOREIGN KEY ("session_id") REFERENCES "public"."assessment_sessions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "assessment_session_sources" ADD CONSTRAINT "assessment_session_sources_source_id_course_source_versions_id_fk" FOREIGN KEY ("source_id") REFERENCES "public"."course_source_versions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "source_passage_unique" ON "course_passages" USING btree ("source_id","passage_key");--> statement-breakpoint
CREATE INDEX "passage_english_fts_idx" ON "course_passages" USING gin (to_tsvector('english', "text"));--> statement-breakpoint
CREATE UNIQUE INDEX "course_source_version_unique" ON "course_source_versions" USING btree ("course_id","document_id","version");--> statement-breakpoint
CREATE INDEX "evidence_runs_session_idx" ON "evidence_runs" USING btree ("session_id");