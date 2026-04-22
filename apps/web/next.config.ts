import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  turbopack: {
    resolveAlias: {
      '@copilotkit/web-inspector': './src/lib/web-inspector-stub.ts',
    },
  },
  webpack(config) {
    const path = require('path');
    config.resolve = config.resolve ?? {};
    config.resolve.alias = {
      ...config.resolve.alias,
      '@copilotkit/web-inspector': path.resolve(__dirname, 'src', 'lib', 'web-inspector-stub.ts'),
    };
    // NFS/shared filesystems exhaust the OS inotify watch limit when webpack
    // tries to watch node_modules + all parent directories. Use polling instead
    // so no inotify watches are needed at all.
    config.watchOptions = {
      poll: 1000,
      aggregateTimeout: 300,
      ignored: /node_modules/,
    };
    return config;
  },
};
export default nextConfig;
