import { pdfjs } from "react-pdf";

const workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.js", import.meta.url).toString();

if (pdfjs.GlobalWorkerOptions.workerSrc !== workerSrc) {
  pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;
}

