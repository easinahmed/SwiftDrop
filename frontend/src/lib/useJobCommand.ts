import { useCallback } from "react";
import { api } from "./api";
import { openWithConfirm } from "./openFile";
import { errorMessage, useStore } from "./store";
import type { Job } from "./types";
import type { JobCommand } from "../components/JobRow";

export function useJobCommand() {
  const toast = useStore((s) => s.toast);
  return useCallback(
    async (command: JobCommand, job: Job) => {
      try {
        if (command === "reveal") await api.revealJob(job.id);
        else if (command === "open") await openWithConfirm((confirmed) => api.openJob(job.id, confirmed));
        else await api.jobAction(command, [job.id]);
      } catch (error) {
        toast("error", errorMessage(error));
      }
    },
    [toast],
  );
}
