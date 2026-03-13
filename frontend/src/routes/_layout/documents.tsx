import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileText, Loader2, Search } from "lucide-react"
import { useEffect } from "react"

import type { DocumentPublic } from "@/client"
import { RagService } from "@/client"
import DeleteDocument from "@/components/Documents/DeleteDocument"
import UploadDocument from "@/components/Documents/UploadDocument"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export const Route = createFileRoute("/_layout/documents")({
  component: Documents,
  head: () => ({
    meta: [{ title: "Documents" }],
  }),
})

function statusBadge(status: string) {
  switch (status) {
    case "done":
      return <Badge variant="default">Done</Badge>
    case "failed":
      return <Badge variant="destructive">Failed</Badge>
    default:
      return (
        <Badge variant="secondary" className="gap-1">
          <Loader2 className="h-3 w-3 animate-spin" />
          Processing
        </Badge>
      )
  }
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return "—"
  return new Date(iso).toLocaleString()
}

function DocumentsTable({ documents }: { documents: DocumentPublic[] }) {
  if (documents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Search className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold">No documents yet</h3>
        <p className="text-muted-foreground">
          Upload a document to start building your knowledge base.
        </p>
      </div>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Filename</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Size</TableHead>
          <TableHead>Uploaded</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="w-12" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {documents.map((doc) => (
          <TableRow key={doc.id}>
            <TableCell className="font-medium">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="truncate max-w-[260px]">{doc.filename}</span>
              </div>
            </TableCell>
            <TableCell className="text-muted-foreground text-xs">
              {doc.file_type.split("/").pop()?.toUpperCase()}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {formatBytes(doc.file_size)}
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">
              {formatDate(doc.created_at)}
            </TableCell>
            <TableCell>{statusBadge(doc.status)}</TableCell>
            <TableCell>
              <DeleteDocument id={doc.id} filename={doc.filename} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function Documents() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ["documents"],
    queryFn: () => RagService.listDocuments({ limit: 100 }),
    refetchInterval: (query) => {
      // Poll every 2 s while any document is still processing.
      const docs = query.state.data?.data ?? []
      const hasPending = docs.some(
        (d) => d.status !== "done" && d.status !== "failed",
      )
      return hasPending ? 2000 : false
    },
  })

  const documents = data?.data ?? []

  // Stop polling as soon as all documents are settled.
  useEffect(() => {
    const allSettled = documents.every(
      (d) => d.status === "done" || d.status === "failed",
    )
    if (allSettled) {
      queryClient.cancelQueries({ queryKey: ["documents"] })
    }
  }, [documents, queryClient])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Documents</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Manage your uploaded documents and knowledge base.
          </p>
        </div>
        <UploadDocument />
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <DocumentsTable documents={documents} />
      )}
    </div>
  )
}

export default Documents
