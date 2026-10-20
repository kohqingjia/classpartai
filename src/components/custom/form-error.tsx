import { FieldError } from "#/components/ui/field";

export function FormError({ error }: { error: unknown }) {
  return typeof error === "string" ? <FieldError>{error}</FieldError> : null;
}
