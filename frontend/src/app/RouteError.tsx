import { Link, useRouteError } from "react-router";
import { Logo } from "./Logo";

export function RouteError({ notFound }: { notFound?: boolean }) {
  const error = useRouteError() as { status?: number; message?: string } | undefined;
  const missing = notFound || error?.status === 404;
  return (
    <div className="grid min-h-[100dvh] place-items-center bg-ink-950 px-6">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-6 w-fit">
          <Logo size={40} />
        </div>
        <h1 className="text-[22px] font-semibold tracking-tight text-fg">
          {missing ? "This view does not exist" : "Something broke while rendering this view"}
        </h1>
        <p className="mt-2 text-[13.5px] leading-relaxed text-fg-muted">
          {missing
            ? "The link may be outdated. Monitoring continues in the background."
            : error?.message ?? "An unexpected error occurred. Monitoring continues in the background."}
        </p>
        <div className="mt-6 flex justify-center gap-2">
          <Link to="/app" className="rounded-[10px] bg-signal px-4 py-2 text-[13px] font-medium text-ink-950">
            Open dashboard
          </Link>
          <Link to="/" className="rounded-[10px] bg-ink-750 px-4 py-2 text-[13px] font-medium text-fg">
            Product overview
          </Link>
        </div>
      </div>
    </div>
  );
}
