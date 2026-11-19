import { useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type Locator = {
  line: number;
  character: number;
  table?: number;
  row?: number;
  cell?: number;
  column?: number;
};

type Disclosure = {
  interpretation: string;
  locator: { start: Locator; end_exclusive: Locator };
};

type RevenueFact = {
  fact_id: string;
  metric_label: string;
  raw_amount: string | null;
  normalized_amount: string | null;
  currency: string | null;
  scale: number | null;
  status: 'verified' | 'provisional';
  applicable_notes: (Disclosure & { number: number; title: string })[];
  comparative: boolean;
  reporting_period: { fiscal_year: number; start: string; end: string };
  parent_table_id: string;
  locators: Record<string, Locator | null>;
  unresolved_requirements: string[];
};

type Source = {
  source_id: string;
  source_hash: string;
  company: string | null;
  accession: string | null;
  form: string | null;
  filing_date: string | null;
  source_url: string | null;
  byte_count: number;
  parser_version: string;
  facts: RevenueFact[];
  comparison?: {
    status: 'compatible' | 'unresolved';
    basis: string | null;
    evidence: (Disclosure & { id: string })[];
    scope_caveats: string[];
    unresolved_requirements: string[];
  };
  diagnostics: { code: string; message: string; fiscal_year?: number }[];
  unresolved_requirements: string[];
  provenance: {
    kind: 'local_original' | 'synthetic';
    input_path: string | null;
    upload_name?: string;
    preserved_at: string;
  };
};

const fields = [
  ['company', 'Company'], ['accession', 'Accession'], ['form', 'Form'],
  ['filing_date', 'Filing date'], ['source_url', 'Source URL'],
] as const;

function provenanceLabel(source: Source) {
  return source.provenance.kind === 'synthetic' ? 'Synthetic input' : 'Declared local original';
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    const problem = await response.json().catch(() => null);
    throw new Error(problem?.error ?? `Request failed (${response.status}).`);
  }
  return response.json();
}

function SourceDetail({ source }: { source: Source }) {
  return (
    <section className="panel detail" aria-labelledby="detail-title">
      <h2 id="detail-title">{source.company ?? 'Source record'}</h2>
      <p className="status">{provenanceLabel(source)} · Source preserved</p>
      <dl>
        <dt>Source ID</dt><dd className="mono">{source.source_id}</dd>
        <dt>SHA-256</dt><dd className="mono">{source.source_hash}</dd>
        <dt>Original size</dt><dd>{source.byte_count.toLocaleString()} bytes</dd>
        <dt>First input</dt>
        <dd>{source.provenance.upload_name ?? source.provenance.input_path ?? 'Unknown'}</dd>
        <dt>Preserved at</dt><dd>{new Date(source.provenance.preserved_at).toLocaleString()}</dd>
      </dl>
      <h3>Filing metadata</h3>
      <p className="muted">These fields show metadata supplied at ingest.</p>
      <dl>
        {fields.map(([key, label]) => (
          <div className="pair" key={key}><dt>{label}</dt><dd>{source[key] ?? 'Unknown'}</dd></div>
        ))}
      </dl>
      <h3>Reported consolidated revenue</h3>
      <dl>
        <dt>Parser version</dt><dd className="mono">{source.parser_version}</dd>
        <dt>Open requirements</dt>
        <dd>{formatRequirements(source.unresolved_requirements)}</dd>
      </dl>
      {source.diagnostics.length > 0 && (
        <ul>{source.diagnostics.map(diagnostic => (
          <li key={`${diagnostic.code}-${diagnostic.fiscal_year ?? 'source'}`}>{diagnostic.message}</li>
        ))}</ul>
      )}
      {source.facts.map(fact => <RevenueDetail fact={fact} key={fact.fact_id} />)}
      {source.comparison && source.facts.length > 0 && (
        <section aria-labelledby="comparison-title">
          <h3 id="comparison-title">FY2022 and FY2023 comparison</h3>
          <p>{source.comparison.basis ?? 'Comparison is unresolved.'}</p>
          {source.comparison.unresolved_requirements.length > 0 && (
            <p>Open requirements · {formatRequirements(source.comparison.unresolved_requirements)}</p>
          )}
          {source.comparison.scope_caveats.map(caveat => <p key={caveat}>{caveat}</p>)}
          {source.comparison.evidence.map(evidence => (
            <DisclosureDetail key={evidence.id} disclosure={evidence} />
          ))}
        </section>
      )}
    </section>
  );
}

function formatRequirements(requirements: string[]) {
  return requirements.map(requirement => requirement.replaceAll('_', ' ')).join(', ') || 'None';
}

function DisclosureDetail({ disclosure, title }: { disclosure: Disclosure; title?: string }) {
  const { start, end_exclusive } = disclosure.locator;
  const lastLine = end_exclusive.line - 1;
  return (
    <p>
      {title && <strong>{title} · </strong>}
      {disclosure.interpretation}{' '}
      <span className="muted">HTML {lastLine === start.line ? `line ${start.line}` : `lines ${start.line}–${lastLine}`}</span>
    </p>
  );
}

const locatorLabels: Record<string, string> = {
  table: 'Statement table', statement_heading: 'Statement heading', metric_label: 'Metric label',
  annual_header: 'Annual period header', year_header: 'Fiscal year header', value: 'Revenue cell',
  unit_header: 'Scale disclosure', currency_measure: 'Currency measure', inline_context: 'Inline XBRL context',
};

function RevenueDetail({ fact }: { fact: RevenueFact }) {
  const { fiscal_year: year, start, end } = fact.reporting_period;
  const [integer, fraction] = (fact.normalized_amount ?? '').split('.');
  const amount = fact.normalized_amount
    ? `${fact.currency} ${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction ? `.${fraction}` : ''}`
    : 'Unknown amount';
  return (
    <details className="fact">
      <summary>FY{year} · {amount} · {fact.status === 'verified' ? 'Verified' : 'Provisional'}</summary>
      <dl>
        <dt>Original label and amount</dt><dd>{fact.metric_label} · {fact.raw_amount || 'Unknown'}</dd>
        <dt>Currency</dt><dd>{fact.currency ?? 'Unknown'}</dd>
        <dt>Scale multiplier</dt><dd>{fact.scale?.toLocaleString() ?? 'Unknown'}</dd>
        <dt>Annual reporting period</dt><dd>{start} through {end}</dd>
        <dt>Reporting basis</dt><dd>As reported in the filing{fact.comparative && ' · Comparative'}</dd>
        <dt>Fact ID</dt><dd className="mono">{fact.fact_id}</dd>
        <dt>Table ID</dt><dd className="mono">{fact.parent_table_id}</dd>
        <dt>Open requirements</dt>
        <dd>{formatRequirements(fact.unresolved_requirements)}</dd>
        {Object.entries(fact.locators).map(([key, location]) => (
          <div className="pair" key={key}>
            <dt>{locatorLabels[key] ?? key}</dt>
            <dd>{location ? [
              location.table && `Table ${location.table}`,
              location.row && `row ${location.row}`,
              location.cell && `cell ${location.cell}`,
              location.column && `column ${location.column}`,
              `line ${location.line}`, `character ${location.character}`,
            ].filter(Boolean).join(', ') : 'Unavailable'}</dd>
          </div>
        ))}
      </dl>
      {fact.applicable_notes?.map(note => (
        <DisclosureDetail key={note.number} disclosure={note} title={`Note ${note.number} · ${note.title}`} />
      ))}
    </details>
  );
}

function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [listError, setListError] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const selected = sources.find(source => source.source_id === selectedId);

  async function refresh() {
    setLoading(true);
    setListError('');
    try {
      const catalogue = await api<{ sources: Source[] }>('/api/sources');
      setSources(catalogue.sources);
    } catch (error) {
      setListError(String(error instanceof Error ? error.message : error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setUploading(true);
    setNotice('');
    setUploadError('');
    try {
      const source = await api<Source>('/api/sources', {
        method: 'POST', body: new FormData(form), headers: { 'X-Frag-Upload': '1' },
      });
      setSources(current => [...current.filter(item => item.source_id !== source.source_id), source]);
      setSelectedId(source.source_id);
      setNotice('Source saved and open for inspection.');
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : String(error));
    } finally {
      setUploading(false);
    }
  }

  return (
    <main>
      <header className="masthead"><span>FRAG</span><h1>Source inspector</h1></header>
      <div className="workspace">
        <aside>
          <section className="panel" aria-labelledby="upload-title">
            <h2 id="upload-title">Upload HTML</h2>
            <form onSubmit={upload}>
              <label>HTML file<input name="file" type="file" accept=".html,.htm,text/html" required /></label>
              <fieldset>
                <legend>Provenance</legend>
                <label className="choice"><input type="radio" name="provenance" value="local_original" required />Local original</label>
                <label className="choice"><input type="radio" name="provenance" value="synthetic" required />Synthetic fixture</label>
              </fieldset>
              <details>
                <summary>Optional filing metadata</summary>
                {fields.map(([name, label]) => (
                  <label key={name}>{label}<input name={name} type={name === 'filing_date' ? 'date' : 'text'} /></label>
                ))}
              </details>
              <button className="primary" disabled={uploading || loading} type="submit">
                {uploading ? 'Preserving…' : 'Preserve source'}
              </button>
              {uploadError && <p className="error" role="alert">{uploadError}</p>}
              <div className="muted" role="status">{notice}</div>
            </form>
          </section>
          <section className="panel" aria-labelledby="sources-title">
            <div className="section-head">
              <h2 id="sources-title">Saved sources <span>({sources.length})</span></h2>
              <button type="button" disabled={loading || uploading} onClick={() => void refresh()}>Refresh</button>
            </div>
            {listError && <p className="error" role="alert">{listError}</p>}
            {loading && <p className="muted" role="status">Loading sources…</p>}
            {!loading && !listError && sources.length === 0 && <p className="muted">No sources saved yet.</p>}
            {sources.length > 0 && <ul className="sources">
              {sources.map(source => (
                <li key={source.source_id}>
                  <button aria-pressed={source.source_id === selectedId} onClick={() => setSelectedId(source.source_id)}>
                    <strong>{source.company ?? source.provenance.upload_name ?? source.source_hash.slice(0, 12)}</strong>
                    <span>{provenanceLabel(source)}</span>
                  </button>
                </li>
              ))}
            </ul>}
          </section>
        </aside>
        {selected ? <SourceDetail source={selected} /> : (
          <section className="panel detail empty"><h2>Inspect a source</h2><p>Upload HTML or select a saved source to inspect its provenance and filing metadata.</p></section>
        )}
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
