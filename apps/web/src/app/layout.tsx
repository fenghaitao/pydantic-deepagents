import type { Metadata } from 'next';
import { CopilotProvider } from '@/components/CopilotProvider';
import '@copilotkit/react-ui/styles.css';
import './globals.css';

export const metadata: Metadata = {
  title: 'pydantic-deep',
  description: 'Local-mode UI for pydantic-deep',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background">
        <CopilotProvider>
          {children}
        </CopilotProvider>
      </body>
    </html>
  );
}
