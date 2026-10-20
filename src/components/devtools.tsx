import { lazy } from "react";

/**
 * Dev-only. Dynamic imports keep the devtools packages and their fonts out of the production
 * transform. It lives here, not in `__root.tsx`, because the route-module boundary test keeps that
 * file to the route object alone.
 */
export const Devtools = import.meta.env.DEV
  ? lazy(async () => {
      const [
        { TanStackDevtools },
        { formDevtoolsPlugin },
        { TanStackRouterDevtoolsPanel },
        { ReactQueryDevtools },
      ] = await Promise.all([
        import("@tanstack/react-devtools"),
        import("@tanstack/react-form-devtools"),
        import("@tanstack/react-router-devtools"),
        import("@tanstack/react-query-devtools"),
      ]);

      return {
        default: function DevtoolsPanel() {
          return (
            <>
              <TanStackDevtools
                plugins={[
                  { name: "TanStack Router", render: <TanStackRouterDevtoolsPanel /> },
                  formDevtoolsPlugin(),
                ]}
              />
              <ReactQueryDevtools />
            </>
          );
        },
      };
    })
  : () => null;
