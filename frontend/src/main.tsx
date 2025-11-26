import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import AppRoutes from './AppRoutes';
import './index.css';

const queryClient = new QueryClient();

const RootApp = () => (
  <>
    <AppRoutes />
    <ReactQueryDevtools initialIsOpen={false} position="bottom-right" />
  </>
);

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RootApp />
    </QueryClientProvider>
  </React.StrictMode>,
);
