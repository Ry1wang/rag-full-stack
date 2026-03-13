import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Upload } from "lucide-react"
import { useState } from "react"

import { RagService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const ACCEPTED_TYPES = [
  "text/plain",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]
const MAX_SIZE_MB = 50

const UploadDocument = () => {
  const [isOpen, setIsOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: (f: File) =>
      RagService.ingestDocument({ formData: { file: f } }),
    onSuccess: () => {
      showSuccessToast("Document uploaded — processing in background")
      setFile(null)
      setIsOpen(false)
      queryClient.invalidateQueries({ queryKey: ["documents"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const handleFileChange = (selected: File | null) => {
    if (!selected) return
    if (!ACCEPTED_TYPES.includes(selected.type)) {
      showErrorToast("Unsupported file type. Please upload PDF, DOCX, or TXT.")
      return
    }
    if (selected.size > MAX_SIZE_MB * 1024 * 1024) {
      showErrorToast(`File exceeds the ${MAX_SIZE_MB} MB limit.`)
      return
    }
    setFile(selected)
  }

  const onDrop = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault()
    setIsDragging(false)
    handleFileChange(e.dataTransfer.files[0] ?? null)
  }

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button className="my-4">
          <Upload className="mr-2 h-4 w-4" />
          Upload Document
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Upload Document</DialogTitle>
          <DialogDescription>
            PDF, DOCX, and TXT files up to {MAX_SIZE_MB} MB. The document will
            be processed in the background — check the list for status updates.
          </DialogDescription>
        </DialogHeader>

        {/* Drop zone — label wraps the hidden file input for native keyboard/click support */}
        <label
          htmlFor="doc-file-input"
          className={`mt-2 flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer ${
            isDragging
              ? "border-primary bg-primary/5"
              : "border-muted-foreground/25 hover:border-primary/50"
          }`}
          onDragOver={(e) => {
            e.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={onDrop}
        >
          <Upload className="mb-3 h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Drag & drop or click to select a file
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            PDF · DOCX · TXT · max {MAX_SIZE_MB} MB
          </p>
          <input
            id="doc-file-input"
            type="file"
            className="hidden"
            accept=".pdf,.docx,.txt"
            onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
          />
        </label>

        {file && (
          <div className="mt-2 rounded-md bg-muted px-3 py-2 text-sm">
            <span className="font-medium">{file.name}</span>
            <span className="ml-2 text-muted-foreground">
              ({formatBytes(file.size)})
            </span>
          </div>
        )}

        {mutation.isPending && (
          <p className="mt-2 text-xs text-muted-foreground animate-pulse">
            Uploading…
          </p>
        )}

        <DialogFooter className="mt-4">
          <DialogClose asChild>
            <Button variant="outline" disabled={mutation.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <LoadingButton
            disabled={!file}
            loading={mutation.isPending}
            onClick={() => file && mutation.mutate(file)}
          >
            Upload
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default UploadDocument
