CREATE TABLE "feedback_deliveries" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"draft_id" uuid NOT NULL,
	"approval_id" uuid NOT NULL,
	"student_id" text NOT NULL,
	"recipient" text NOT NULL,
	"state" text NOT NULL,
	"attempts" integer NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "feedback_delivery_attempts" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"delivery_id" uuid NOT NULL,
	"attempt" integer NOT NULL,
	"state" text NOT NULL,
	"reason" text,
	"message_id" text,
	"started_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "participation_drafts" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"session_id" uuid NOT NULL,
	"version" integer NOT NULL,
	"parent_id" uuid,
	"origin" text NOT NULL,
	"content" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "participation_runs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"session_id" uuid NOT NULL,
	"status" text NOT NULL,
	"progress" jsonb NOT NULL,
	"manifest" jsonb NOT NULL,
	"stop_reason" text,
	"deadline_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "professor_approvals" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"draft_id" uuid NOT NULL,
	"professor_id" text NOT NULL,
	"digest" text NOT NULL,
	"acknowledgement" text NOT NULL,
	"issue_ids" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"invalidated_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "roster_recipients" (
	"session_id" uuid NOT NULL,
	"student_id" text NOT NULL,
	"email" text NOT NULL,
	"revision" integer NOT NULL,
	CONSTRAINT "roster_recipients_session_id_student_id_pk" PRIMARY KEY("session_id","student_id")
);
--> statement-breakpoint
ALTER TABLE "feedback_deliveries" ADD CONSTRAINT "feedback_deliveries_draft_id_participation_drafts_id_fk" FOREIGN KEY ("draft_id") REFERENCES "public"."participation_drafts"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "feedback_deliveries" ADD CONSTRAINT "feedback_deliveries_approval_id_professor_approvals_id_fk" FOREIGN KEY ("approval_id") REFERENCES "public"."professor_approvals"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "feedback_delivery_attempts" ADD CONSTRAINT "feedback_delivery_attempts_delivery_id_feedback_deliveries_id_fk" FOREIGN KEY ("delivery_id") REFERENCES "public"."feedback_deliveries"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "participation_drafts" ADD CONSTRAINT "participation_drafts_session_id_assessment_sessions_id_fk" FOREIGN KEY ("session_id") REFERENCES "public"."assessment_sessions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "participation_runs" ADD CONSTRAINT "participation_runs_session_id_assessment_sessions_id_fk" FOREIGN KEY ("session_id") REFERENCES "public"."assessment_sessions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "professor_approvals" ADD CONSTRAINT "professor_approvals_draft_id_participation_drafts_id_fk" FOREIGN KEY ("draft_id") REFERENCES "public"."participation_drafts"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "professor_approvals" ADD CONSTRAINT "professor_approvals_professor_id_user_id_fk" FOREIGN KEY ("professor_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "roster_recipients" ADD CONSTRAINT "roster_recipients_session_id_assessment_sessions_id_fk" FOREIGN KEY ("session_id") REFERENCES "public"."assessment_sessions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "one_delivery_per_draft_student" ON "feedback_deliveries" USING btree ("draft_id","student_id");--> statement-breakpoint
CREATE UNIQUE INDEX "delivery_attempt_unique" ON "feedback_delivery_attempts" USING btree ("delivery_id","attempt");--> statement-breakpoint
CREATE UNIQUE INDEX "participation_draft_version_unique" ON "participation_drafts" USING btree ("session_id","version");--> statement-breakpoint
CREATE INDEX "participation_runs_session_idx" ON "participation_runs" USING btree ("session_id");--> statement-breakpoint
CREATE UNIQUE INDEX "one_current_approval_per_draft" ON "professor_approvals" USING btree ("draft_id") WHERE "professor_approvals"."invalidated_at" is null;