import { getRouteApi, useRouter, Link } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "@tanstack/react-form-start";
import { Trash2, Plus, Upload, CheckCircle } from "lucide-react";
import { useRef } from "react";
import { toast } from "sonner";

import { createNote, deleteNote } from "#/features/notes/server-fns";
import { CreateNoteInput } from "#/features/notes/schema";
import { createUploadUrl } from "#/features/uploads/server-fns";
import { FormError } from "#/components/custom/form-error";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import { FieldError } from "#/components/ui/field";
import { Skeleton } from "#/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "#/components/ui/table";
import { Page } from "#/components/custom/page";

const routeApi = getRouteApi("/_authenticated/dashboard");

export function DashboardPage() {
  const { user } = routeApi.useRouteContext();
  const { notes } = routeApi.useLoaderData();
  const router = useRouter();

  const form = useForm({
    defaultValues: { title: "" },
    validators: { onSubmit: CreateNoteInput },
    onSubmit: async ({ value, formApi }) => {
      try {
        await createNote({ data: { title: value.title } });
      } catch (error) {
        formApi.setErrorMap({
          onSubmit: {
            form: error instanceof Error ? error.message : "Failed to create note",
            fields: {},
          },
        });
        return;
      }

      form.reset();
      await router.invalidate();
    },
  });

  const deleteNoteMutation = useMutation({
    mutationFn: (id: number) => deleteNote({ data: { id } }),
    onSuccess: () => router.invalidate(),
    onError: error => toast.error(error.message || "Failed to delete note"),
  });

  return (
    <Page
      eyebrow="Dashboard"
      title={`Welcome, ${user.name?.trim() || user.email}`}
      description="A protected route exercising the full loop: session, server functions, database, uploads."
    >
      <section className="flex flex-col">
        <dl className="mt-10 grid gap-6 border-y border-border py-6 sm:grid-cols-3">
          <div>
            <dt className="font-mono text-xs tracking-caps text-muted-foreground uppercase">
              Session
            </dt>
            <dd className="mt-2 text-lg font-medium">Active</dd>
          </div>
          <div>
            <dt className="font-mono text-xs tracking-caps text-muted-foreground uppercase">
              Email
            </dt>
            <dd className="mt-2 truncate text-lg font-medium">{user.email}</dd>
          </div>
          <div>
            <dt className="font-mono text-xs tracking-caps text-muted-foreground uppercase">
              Notes
            </dt>
            <dd className="mt-2 text-lg font-medium">{notes.length}</dd>
          </div>
        </dl>

        <section className="mt-12" aria-label="Notes">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-heading text-lg font-semibold tracking-tight">Notes</h2>
          </div>

          <form
            className="mt-4"
            onSubmit={e => {
              e.preventDefault();
              void form.handleSubmit();
            }}
          >
            <div className="flex gap-2">
              <form.Field name="title">
                {field => (
                  <Input
                    placeholder="New note title…"
                    value={field.state.value}
                    onChange={e => field.handleChange(e.target.value)}
                    onBlur={field.handleBlur}
                    aria-invalid={field.state.meta.errors.length > 0}
                    className="flex-1"
                  />
                )}
              </form.Field>
              <form.Subscribe selector={s => s.isSubmitting || s.values.title.trim().length === 0}>
                {isDisabled => (
                  <Button type="submit" disabled={isDisabled} size="sm">
                    <Plus className="size-4" />
                    Add
                  </Button>
                )}
              </form.Subscribe>
            </div>

            <form.Field name="title">
              {field => <FieldError errors={field.state.meta.errors} className="mt-2" />}
            </form.Field>
          </form>

          <form.Subscribe selector={s => s.errorMap.onSubmit}>
            {formError => <FormError error={formError} />}
          </form.Subscribe>

          {notes.length === 0 ? (
            <p className="py-6 text-sm text-muted-foreground">
              No notes yet. Add your first one above.
            </p>
          ) : (
            <Table className="mt-4">
              <TableHeader>
                <TableRow>
                  <TableHead>Note</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {notes.map(note => (
                  <TableRow key={note.id}>
                    <TableCell>{note.title}</TableCell>
                    <TableCell>
                      {note.createdAt ? new Date(note.createdAt).toLocaleDateString() : "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <Button
                          type="button"
                          variant="destructive"
                          size="icon-sm"
                          disabled={
                            deleteNoteMutation.isPending && deleteNoteMutation.variables === note.id
                          }
                          aria-label={`Delete note: ${note.title}`}
                          onClick={() => deleteNoteMutation.mutate(note.id)}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </section>

        <FileUploadCard />

        <div className="mt-12 border-t border-border pt-6">
          <Link
            to="/settings"
            className="text-sm font-medium underline decoration-border underline-offset-4 hover:decoration-foreground"
          >
            Account settings
          </Link>
        </div>
      </section>
    </Page>
  );
}

/**
 * Route-level pending view (`/dashboard` awaits `listNotes`): the same Page shell and section
 * rhythm with the data-dependent values held as skeletons, so the swap to real data does not
 * shift the layout.
 */
export function DashboardPageSkeleton() {
  return (
    <Page
      eyebrow="Dashboard"
      title={<Skeleton className="h-9 w-72 md:h-10 md:w-80" />}
      description="A protected route exercising the full loop: session, server functions, database, uploads."
    >
      <section className="flex flex-col" aria-busy="true">
        <output className="sr-only">Loading dashboard</output>

        <dl className="mt-10 grid gap-6 border-y border-border py-6 sm:grid-cols-3">
          {["Session", "Email", "Notes"].map(label => (
            <div key={label}>
              <dt className="font-mono text-xs tracking-caps text-muted-foreground uppercase">
                {label}
              </dt>
              <dd className="mt-2">
                <Skeleton className="h-7 w-24" />
              </dd>
            </div>
          ))}
        </dl>

        <section className="mt-12" aria-label="Notes">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-heading text-lg font-semibold tracking-tight">Notes</h2>
          </div>
          <div className="mt-4 flex gap-2">
            <Skeleton className="h-9 flex-1" />
            <Skeleton className="h-9 w-20" />
          </div>
          <div className="mt-4 space-y-2">
            {[0, 1, 2].map(row => (
              <Skeleton key={row} className="h-10 w-full" />
            ))}
          </div>
        </section>

        <section className="mt-12" aria-label="File upload">
          <h2 className="font-heading text-lg font-semibold tracking-tight">File upload</h2>
          <Skeleton className="mt-2 h-5 w-full max-w-xl" />
          <Skeleton className="mt-4 h-8 w-32" />
        </section>

        <div className="mt-12 border-t border-border pt-6">
          <Skeleton className="h-5 w-36" />
        </div>
      </section>
    </Page>
  );
}

function FileUploadCard() {
  const inputRef = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const { url, key } = await createUploadUrl({
        data: { filename: file.name, contentType: file.type, size: file.size },
      });

      const putRes = await fetch(url, {
        method: "PUT",
        headers: { "Content-Type": file.type },
        body: file,
      });
      if (!putRes.ok) throw new Error("Upload to storage failed");

      return key;
    },
    onSettled: () => {
      if (inputRef.current) inputRef.current.value = "";
    },
  });

  return (
    <section className="mt-12" aria-label="File upload">
      <h2 className="font-heading text-lg font-semibold tracking-tight">File upload</h2>
      <p className="mt-2 max-w-xl text-sm text-muted-foreground">
        Presigned PUT upload via MinIO. Images and PDFs up to 10 MB.
      </p>

      {upload.status === "success" ? (
        <p className="mt-4 flex items-center gap-2 text-sm">
          <CheckCircle className="size-4" />
          Uploaded: <code className="font-mono text-xs break-all">{upload.data}</code>
        </p>
      ) : upload.status === "error" ? (
        <p className="mt-4 text-sm text-destructive">{upload.error.message}</p>
      ) : null}

      <div className="mt-4">
        <Input
          ref={inputRef}
          type="file"
          accept="image/*,application/pdf,text/plain"
          className="hidden"
          onChange={e => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
          }}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={upload.isPending}
          onClick={() => inputRef.current?.click()}
        >
          <Upload className="size-4" />
          {upload.isPending ? "Uploading…" : "Choose file"}
        </Button>
      </div>
    </section>
  );
}
