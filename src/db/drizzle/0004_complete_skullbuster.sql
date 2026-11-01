ALTER TABLE "feedback_deliveries" DROP CONSTRAINT "feedback_deliveries_approval_id_professor_approvals_id_fk";
--> statement-breakpoint
ALTER TABLE "feedback_deliveries" ADD CONSTRAINT "feedback_deliveries_approval_id_professor_approvals_id_fk" FOREIGN KEY ("approval_id") REFERENCES "public"."professor_approvals"("id") ON DELETE cascade ON UPDATE no action;