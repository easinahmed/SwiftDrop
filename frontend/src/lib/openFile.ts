import { ApiError, CONFIRM_OPEN } from "./api";
import { errorMessage, useStore } from "./store";

/**
 * Run an "open file" call. If the engine says the file can run code, ask first and
 * retry with confirmed=true when the user agrees.
 */
export async function openWithConfirm(open: (confirmed: boolean) => Promise<unknown>): Promise<void> {
  const { toast, setOpenConfirm } = useStore.getState();
  try {
    await open(false);
  } catch (error) {
    if (error instanceof ApiError && error.message === CONFIRM_OPEN) {
      setOpenConfirm({
        name: error.fileName ?? "This file",
        run: () => {
          open(true).catch((e: unknown) => toast("error", errorMessage(e)));
        },
      });
      return;
    }
    toast("error", errorMessage(error));
  }
}
