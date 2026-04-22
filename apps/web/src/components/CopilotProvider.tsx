'use client';

import { CopilotKit } from '@copilotkit/react-core';

export function CopilotProvider({ children }: { children: React.ReactNode }) {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit" agent="pydantic_deep_agent" showDevConsole={false}>
      {children}
    </CopilotKit>
  );
}
