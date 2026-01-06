import { create } from "zustand";

import type { BookState } from "@/lib/bookPayload";

export type BookStatus = "connecting" | "live" | "error";

interface BookStoreState {
  books: Record<string, BookState | undefined>;
  status: Record<string, BookStatus | undefined>;
  frame: number;
  setBook: (assetId: string, book: BookState) => void;
  setStatus: (assetId: string, status: BookStatus) => void;
  setStatusBulk: (assetIds: Iterable<string>, status: BookStatus) => void;
  setBooksBulk: (updates: Record<string, BookState>, status?: BookStatus) => void;
  bumpFrame: () => void;
  clearBook: (assetId: string) => void;
}

export const useBookStore = create<BookStoreState>((set) => ({
  books: {},
  status: {},
  frame: 0,
  setBook: (assetId, book) =>
    set((state) => ({
      books: { ...state.books, [assetId]: book },
    })),
  setStatus: (assetId, status) =>
    set((state) => ({
      status: { ...state.status, [assetId]: status },
    })),
  setStatusBulk: (assetIds, status) =>
    set((state) => {
      const nextStatus = { ...state.status };
      for (const assetId of assetIds) {
        nextStatus[assetId] = status;
      }
      return { status: nextStatus };
    }),
  setBooksBulk: (updates, status) =>
    set((state) => {
      const nextBooks = { ...state.books };
      Object.keys(updates).forEach((assetId) => {
        nextBooks[assetId] = updates[assetId];
      });
      if (!status) {
        return { books: nextBooks };
      }
      const nextStatus = { ...state.status };
      Object.keys(updates).forEach((assetId) => {
        nextStatus[assetId] = status;
      });
      return { books: nextBooks, status: nextStatus };
    }),
  bumpFrame: () =>
    set((state) => ({
      frame: (state.frame + 1) % 1_000_000,
    })),
  clearBook: (assetId) =>
    set((state) => {
      if (!state.books[assetId] && !state.status[assetId]) return state;
      const nextBooks = { ...state.books };
      const nextStatus = { ...state.status };
      delete nextBooks[assetId];
      delete nextStatus[assetId];
      return { books: nextBooks, status: nextStatus };
    }),
}));
