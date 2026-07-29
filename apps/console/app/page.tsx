"use client";

import useSWR from "swr";

type Health = {
  status: string;
  version: string;
  environment: string;
  database: string;
  providers: string[];
};

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export default function Overview() {
  const { data, error, isLoading } = useSWR<Health>("/api/health", fetcher, {
    refreshInterval: 30_000,
  });

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold tracking-tight">Overview</h1>
      <p className="mt-1 text-sm text-slate-600">
        Platform status. Request volume, spend and error rate land here with OBS-004.
      </p>

      <section className="mt-6 rounded-lg border border-rule bg-white p-5">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-steel">
          API health
        </h2>

        {isLoading && <p className="mt-3 text-sm text-slate-500">Checking…</p>}

        {error && (
          <p className="mt-3 text-sm text-signal">
            Cannot reach the API. Is it running on :8000? Try <code>make api</code>.
          </p>
        )}

        {data && (
          <dl className="mt-3 grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
            <Row label="Status" value={data.status} />
            <Row label="Version" value={data.version} />
            <Row label="Environment" value={data.environment} />
            <Row label="Database" value={data.database} />
            <Row label="Providers" value={data.providers.join(", ")} />
          </dl>
        )}
      </section>

      <p className="mt-6 text-sm text-slate-600">
        Next up: <strong>GW-001</strong> provider abstraction, then <strong>GW-002</strong>{" "}
        the chat pipeline. Search the repo for <code>TODO(</code> to see what the scaffold
        left open.
      </p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-mono text-[13px]">{value}</dd>
    </>
  );
}
