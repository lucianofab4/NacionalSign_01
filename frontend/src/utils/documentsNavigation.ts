import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

import type { DocumentRecord } from "../api";

export function useDocumentNavigation() {
  const navigate = useNavigate();
  return useCallback(
    (doc: Pick<DocumentRecord, "id" | "status">) => {
      const status = (doc.status || "").toLowerCase();
      if (status === "signed" || status === "completed") {
        navigate(`/documents/${doc.id}/signed`);
      } else {
        navigate(`/documents/${doc.id}`);
      }
    },
    [navigate],
  );
}
