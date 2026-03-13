import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
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
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

interface DeleteDocumentProps {
  id: string
  filename: string
}

const DeleteDocument = ({ id, filename }: DeleteDocumentProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: () => RagService.deleteDocument({ documentId: id }),
    onSuccess: () => {
      showSuccessToast("Document deleted successfully")
      setIsOpen(false)
      queryClient.invalidateQueries({ queryKey: ["documents"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="text-destructive hover:text-destructive"
        onClick={() => setIsOpen(true)}
        aria-label={`Delete ${filename}`}
      >
        <Trash2 className="h-4 w-4" />
      </Button>

      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete Document</DialogTitle>
            <DialogDescription>
              <strong>{filename}</strong> and all its embeddings will be
              permanently deleted. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="mt-4">
            <DialogClose asChild>
              <Button variant="outline" disabled={mutation.isPending}>
                Cancel
              </Button>
            </DialogClose>
            <LoadingButton
              variant="destructive"
              loading={mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              Delete
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

export default DeleteDocument
