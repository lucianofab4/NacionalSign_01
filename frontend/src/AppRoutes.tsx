import { BrowserRouter, Routes, Route } from "react-router-dom";
import App from "./App";
import DocumentDetailPage from "./pages/DocumentDetailPage";
import DocumentSignedView from "./pages/DocumentSignedView";
import PublicSignaturePage from "./pages/PublicSignaturePage";
import ActivateCustomerPage from "./pages/ActivateCustomerPage";

export default function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/documentos/novo" element={<App />} />
        <Route path="/documentos/:id/gerenciar" element={<App />} />
        <Route path="/documentos/:id" element={<DocumentDetailPage />} />
        <Route path="/documents/:id/signed" element={<DocumentSignedView />} />
        <Route path="/public/sign/:token" element={<PublicSignaturePage />} />
        <Route path="/public/signatures/:token" element={<PublicSignaturePage />} />
        <Route path="/public/signatures/:token/page" element={<PublicSignaturePage />} />
        <Route path="/activate/:token" element={<ActivateCustomerPage />} />
        <Route path="/*" element={<App />} />
      </Routes>
    </BrowserRouter>
  );
}
