import { saveAs } from 'file-saver';
import JSZip from 'jszip';

/** Baixa um único arquivo (Blob) com nome */
export function saveBlob(blob: Blob, filename: string) {
  saveAs(blob, filename);
}

/** Faz download via fetch e retorna Blob */
export async function fetchAsBlob(url: string): Promise<Blob> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Falha ao baixar: ${url}`);
  return await res.blob();
}

/** Zipa arquivos (nome -> Blob) e retorna um Blob ZIP */
export async function zipFiles(files: Record<string, Blob>): Promise<Blob> {
  const zip = new JSZip();
  for (const [name, blob] of Object.entries(files)) {
    zip.file(name, blob);
  }
  return await zip.generateAsync({ type: 'blob' });
}
