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
  applicable_notes: (Disclosure & { id?: string; number: number; title: string })[];
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
  parser_version: string | null;
  facts: RevenueFact[];
  comparison?: {
    status: 'compatible' | 'unresolved';
    basis: string | null;
    detail?: string;
    fact_ids?: string[];
    evidence: (Disclosure & { id: string })[];
    scope_caveats: string[];
    unresolved_requirements: string[];
  };
  diagnostics?: { code: string; message: string; fiscal_year?: number }[];
  unresolved_requirements: string[];
  provenance: {
    kind: 'local_original' | 'synthetic' | 'sec_download';
    input_path: string | null;
    upload_name?: string;
    preserved_at: string;
  };
};

type FilingMatch = {
  cik: string;
  company: string;
  accession: string;
  form: string;
  filing_date: string;
  report_date: string | null;
};

const fields = [
  ['company', 'Company'], ['accession', 'Accession'], ['form', 'Form'],
  ['filing_date', 'Filing date'], ['source_url', 'Source URL'],
] as const;

function provenanceLabel(source: Source) {
  if (source.provenance.kind === 'sec_download') return 'Downloaded from SEC EDGAR';
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

function secRequest<T>(path: string, data?: Record<string, string>): Promise<T> {
  const headers = new Headers({ 'X-Frag-Download': '1' });
  if (data) headers.set('Content-Type', 'application/json');
  return api<T>(path, { method: 'POST', headers, body: data && JSON.stringify(data) });
}

type GrowthIssue = {
  code: 'absent' | 'unverified' | 'incompatible';
  role: 'prior' | 'current' | null;
  fiscal_year: number | null;
  detail: string;
};

type GrowthResult = {
  prior_year: number;
  current_year: number;
  percent: { unit: 'percent'; value: string } | null;
  absolute_change: { currency: string; value: string } | null;
  formula: string;
  operands: (RevenueFact & { role: 'prior' | 'current' })[];
  issues: GrowthIssue[];
  trace: { operation: string; inputs: string[]; result: string }[];
  citations: { id: string; title: string; href?: string }[];
  comparison_basis: string | null;
  scope_caveats: string[];
  evidence_version: string | null;
};

function GrowthCalculator({ source }: { source: Source }) {
  const comparativeYears = source.facts.filter(fact => fact.comparative).map(fact => fact.reporting_period.fiscal_year);
  const priorYear = comparativeYears.length ? Math.max(...comparativeYears) : undefined;
  const currentYear = source.facts.find(fact => !fact.comparative)?.reporting_period.fiscal_year;
  const [prior, setPrior] = useState(String(priorYear ?? (currentYear ? currentYear - 1 : 2022)));
  const [current, setCurrent] = useState(String(currentYear ?? (priorYear ? priorYear + 1 : 2023)));
  const [result, setResult] = useState<GrowthResult>();
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const path = `/api/sources/${encodeURIComponent(source.source_id)}/growth`;

  function editYear(setYear: (year: string) => void, year: string) {
    setYear(year);
    setResult(undefined);
    setError('');
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setResult(undefined);
    setError('');
    try {
      const query = new URLSearchParams({ prior, current });
      setResult(await api<GrowthResult>(`${path}?${query}`));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Revenue growth calculation failed.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="growth-title">
      <h3 id="growth-title">Revenue growth</h3>
      <form onSubmit={submit}>
        <fieldset className="growth-years" disabled={pending}>
          <label>Prior fiscal year<input type="number" min="1" max="9999" required value={prior}
            onChange={event => editYear(setPrior, event.target.value)} /></label>
          <label>Current fiscal year<input type="number" min="1" max="9999" required value={current}
            onChange={event => editYear(setCurrent, event.target.value)} /></label>
        </fieldset>
        <button type="submit" disabled={pending}>Calculate revenue growth</button>
      </form>
      {pending && <p role="status">Calculating revenue growth…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {result && <GrowthAnswer result={result} path={path} />}
    </section>
  );
}

function GrowthAnswer({ result, path }: { result: GrowthResult; path?: string }) {
  const citationQuery = new URLSearchParams({
    prior: String(result.prior_year), current: String(result.current_year),
  });
  const operands = result.operands.filter(fact => fact.status === 'verified' && fact.normalized_amount !== null);
  const operandRows = operands.map(fact => (
    <p key={fact.fact_id}>
      {fact.role} · FY{fact.reporting_period.fiscal_year} · {fact.currency} {fact.normalized_amount}
      {' · '}<span className="mono">{fact.fact_id}</span>
    </p>
  ));
  return (
    <div className="growth-result" aria-live="polite">
      {result.percent && <p className="growth-value">{result.percent.value}%</p>}
      {result.absolute_change && (
        <>
          <p>Percentage undefined because prior revenue is zero.</p>
          <p>Absolute revenue change · {result.absolute_change.currency} {result.absolute_change.value}</p>
        </>
      )}
      {result.issues.map(issue => (
        <p key={issue.role ?? 'comparison'}>{issue.detail}</p>
      ))}
      {result.trace.length > 0 && (
        <>
          <p>FY{result.prior_year} to FY{result.current_year} · {result.formula}</p>
          {result.comparison_basis && <p>{result.comparison_basis}</p>}
          {result.scope_caveats.map(caveat => <p key={caveat}>{caveat}</p>)}
          <details>
            <summary>Operation trace and operands</summary>
            <p>Evidence version · {result.evidence_version}</p>
            {operandRows}
            <ol>{result.trace.map(step => (
              <li key={step.operation}>{step.operation} ({step.inputs.join(', ')}) = {step.result}</li>
            ))}</ol>
          </details>
        </>
      )}
      {result.trace.length === 0 && operands.length > 0 && (
        <>
          <h4>Supported observations</h4>
          {operandRows}
        </>
      )}
      {result.citations.length > 0 && (
        <>
          <h4>Original filing evidence</h4>
          <ul>{result.citations.map(citation => (
            <li key={citation.id}>
              <a href={citation.href ?? `${path}/citations/${encodeURIComponent(citation.id)}?${citationQuery}`}
                target="_blank" rel="noopener noreferrer">{citation.title}</a>
            </li>
          ))}</ul>
        </>
      )}
    </div>
  );
}

type RevenueAnswer =
  | { status: 'answered'; fiscal_year: number; fact: RevenueFact; citations: { id: string; title: string }[] }
  | { status: 'evidence_unavailable'; fiscal_year: number; message: string; citations: { id: string; title: string }[] }
  | (GrowthResult & { status: 'calculated' | 'undefined_zero_baseline' | 'unavailable'; operation: 'growth' })
  | { status: 'clarify' | 'model_unavailable' | 'model_timeout' | 'invalid_plan'; message: string };

type CitationLink = { title: string; href: string };

function LookupCitations({ citations }: { citations: CitationLink[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="lookup-citations">
      <p><strong>Original filing evidence</strong></p>
      <ul>
        {citations.map(({ title, href }) => (
          <li key={href}>
            <a href={href} target="_blank" rel="noopener noreferrer">
              {title.replace(/^(Note (\d+) · )Note \2\s*:\s*/i, '$1')}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RevenueChat({ source }: { source: Source }) {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<RevenueAnswer>();
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const year = (source.facts.find(fact => !fact.comparative) ?? source.facts[0])?.reporting_period.fiscal_year ?? 2023;
  const sourcePath = `/api/sources/${encodeURIComponent(source.source_id)}`;
  const path = `${sourcePath}/lookup`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setResult(undefined);
    setError('');
    try {
      setResult(await api<RevenueAnswer>(path, {
        method: 'POST',
        headers: { 'X-Frag-Ask': '1', 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      }));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Revenue question failed.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="lookup-title">
      <h3 id="lookup-title">Ask the filing</h3>
      <form onSubmit={submit}>
        <label>
          Question about annual revenue or growth
          <input value={question} onChange={event => {
            setQuestion(event.target.value);
            setResult(undefined);
            setError('');
          }} placeholder={`What was revenue in FY${year}?`} autoComplete="off"
            required maxLength={300} disabled={pending} />
        </label>
        <button type="submit" disabled={pending || !question.trim()}>Ask</button>
      </form>
      <div className="lookup-result" aria-live="polite">
        {pending && <p>Checking the selected filing…</p>}
        {error && <p className="error">{error}</p>}
        {result?.status === 'answered' && (
          <>
            <p><strong>FY{result.fiscal_year} reported consolidated revenue</strong></p>
            <p className="growth-value">{revenueAmount(result.fact)}</p>
          </>
        )}
        {result && 'operation' in result && <GrowthAnswer result={result} path={`${sourcePath}/growth`} />}
        {result && 'message' in result && <p>{result.message}</p>}
        {(result?.status === 'answered' || result?.status === 'evidence_unavailable') && (
          <LookupCitations citations={result.citations.map(citation => ({
            title: citation.title,
            href: `${path}/citations/${result.fiscal_year}/${encodeURIComponent(citation.id)}`,
          }))} />
        )}
      </div>
    </section>
  );
}

type CollectionResult =
  | { status: 'answered'; request: { company: string; fiscal_year: number }; fact: RevenueFact;
      citations: CitationLink[]; unresolved_requirements?: string[] }
  | { status: 'conflicting_evidence'; message: string;
      alternatives: { fact: RevenueFact; citation: CitationLink }[] }
  | (GrowthResult & { status: 'calculated' | 'undefined_zero_baseline'; request: { company: string } })
  | { status: 'clarify' | 'evidence_unavailable'; message: string;
      budget_limit?: 'time' | 'calls';
      observations?: { fact: RevenueFact & { basis: string }; citation: CitationLink }[];
      comparisons?: { source_id: string; scope_caveats: string[] }[];
      issues?: { detail: string; requirements?: string[] }[]; citations?: CitationLink[] };

function CollectionLookup() {
  const [result, setResult] = useState<CollectionResult>();
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const question = fields.get('question');
    const mode = fields.get('mode');
    setPending(true);
    setResult(undefined);
    setError('');
    try {
      setResult(await api<CollectionResult>('/api/collection/lookup', {
        method: 'POST',
        headers: { 'X-Frag-Ask': '1', 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, mode }),
      }));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Collection search failed.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="panel collection" aria-labelledby="collection-title">
      <h2 id="collection-title">Ask the collection</h2>
      <form onSubmit={submit} onChange={() => { setResult(undefined); setError(''); }}>
        <label>
          Question about annual company revenue or growth
          <input name="question" placeholder="What was Microsoft's revenue in FY2023?"
            autoComplete="off" required maxLength={300} disabled={pending} />
        </label>
        <label>
          Retrieval mode
          <select name="mode" disabled={pending}>
            <option value="one-pass">One pass</option>
            <option value="bounded">Bounded recovery</option>
          </select>
        </label>
        <button className="primary" type="submit" disabled={pending}>Search collection</button>
      </form>
      <div className="lookup-result" aria-live="polite">
        {pending && <p>Searching preserved filings…</p>}
        {error && <p className="error">{error}</p>}
        {result?.status === 'answered' && (
          <>
            <p><strong>{result.request.company} FY{result.request.fiscal_year} reported consolidated revenue</strong></p>
            <p className="growth-value">{revenueAmount(result.fact)}</p>
            <LookupCitations citations={result.citations} />
            {!!result.unresolved_requirements?.length && (
              <p>Unavailable disclosures · {result.unresolved_requirements.join(', ')}.</p>
            )}
          </>
        )}
        {(result?.status === 'calculated' || result?.status === 'undefined_zero_baseline') && (
          <>
            <p><strong>{result.request.company} reported consolidated revenue growth</strong></p>
            <GrowthAnswer result={result} />
          </>
        )}
        {result && 'message' in result && <p>{result.message}</p>}
        {result?.status === 'evidence_unavailable' && (
          <>
            {result.budget_limit && <p>Recovery reached its {result.budget_limit === 'calls' ? 'call' : 'time'} limit.</p>}
            {result.issues?.map((issue, index) => (
              <p key={index}>{issue.detail}{issue.requirements?.length
                ? ` Missing evidence · ${issue.requirements.join(', ')}.` : ''}</p>
            ))}
            {!!result.observations?.length && (
              <ul>{result.observations.map(({ fact, citation }) => (
                <li key={fact.fact_id}>
                  {revenueAmount(fact)} · {fact.basis}{' '}
                  <a href={citation.href} target="_blank" rel="noopener noreferrer">{citation.title}</a>
                </li>
              ))}</ul>
            )}
            {result.comparisons?.flatMap(comparison => comparison.scope_caveats.map(caveat => (
              <p key={`${comparison.source_id}:${caveat}`}>{caveat}</p>
            )))}
            {result.citations?.map(citation => (
              <a key={citation.href} href={citation.href} target="_blank" rel="noopener noreferrer">{citation.title}</a>
            ))}
          </>
        )}
        {result?.status === 'conflicting_evidence' && (
          <ul>{result.alternatives.map(({ fact, citation }) => (
            <li key={fact.fact_id}>{revenueAmount(fact)} ·{' '}
              <a href={citation.href} target="_blank" rel="noopener noreferrer">{citation.title}</a>
            </li>
          ))}</ul>
        )}
      </div>
    </section>
  );
}

function SourceDetail({ source }: { source: Source }) {
  const diagnostics = source.diagnostics ?? [];
  const comparisonIds = source.comparison?.fact_ids;
  const comparisonYears = source.facts
    .filter(fact => comparisonIds?.includes(fact.fact_id) ?? (source.comparison?.status === 'compatible'))
    .map(fact => fact.reporting_period.fiscal_year)
    .sort((a, b) => a - b);
  return (
    <section className="panel detail" aria-labelledby="detail-title">
      <h2 id="detail-title">{source.company ?? 'Source record'}</h2>
      <p className="status">{provenanceLabel(source)} · Source preserved</p>
      <dl>
        <dt>Source ID</dt><dd className="mono">{source.source_id}</dd>
        <dt>SHA-256</dt><dd className="mono">{source.source_hash}</dd>
        <dt>Original size</dt><dd>{source.byte_count.toLocaleString()} bytes</dd>
        <dt>First input</dt>
        <dd>{source.provenance.kind === 'sec_download'
          ? source.source_url ?? 'Unknown'
          : source.provenance.upload_name ?? source.provenance.input_path ?? 'Unknown'}</dd>
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
        <dt>Parser version</dt><dd className="mono">{source.parser_version ?? 'Unavailable'}</dd>
        <dt>Open requirements</dt>
        <dd>{formatRequirements(source.unresolved_requirements)}</dd>
      </dl>
      {source.parser_version === null && <p className="muted">Revenue extraction is unavailable for this saved source.</p>}
      {diagnostics.length > 0 && (
        <ul>{diagnostics.map(diagnostic => (
          <li key={`${diagnostic.code}-${diagnostic.fiscal_year ?? 'source'}`}>{diagnostic.message}</li>
        ))}</ul>
      )}
      {source.facts.map(fact => <RevenueDetail fact={fact} key={fact.fact_id} />)}
      {source.comparison && source.facts.length > 0 && (
        <section aria-labelledby="comparison-title">
          <h3 id="comparison-title">{comparisonYears.length === 2
            ? `FY${comparisonYears[0]} and FY${comparisonYears[1]} comparison` : 'Revenue comparison'}</h3>
          <p>{source.comparison.basis ?? source.comparison.detail ?? 'Comparison is unresolved.'}</p>
          {source.comparison.unresolved_requirements.length > 0 && (
            <p>Open requirements · {formatRequirements(source.comparison.unresolved_requirements)}</p>
          )}
          {source.comparison.scope_caveats.map(caveat => <p key={caveat}>{caveat}</p>)}
          {source.comparison.evidence.map(evidence => (
            <DisclosureDetail key={evidence.id} disclosure={evidence} />
          ))}
        </section>
      )}
      <GrowthCalculator key={source.source_id} source={source} />
      <RevenueChat key={`lookup-${source.source_id}`} source={source} />
    </section>
  );
}

function formatRequirements(requirements: string[]) {
  return requirements.map(requirement => requirement.replaceAll('_', ' ')).join(', ') || 'None';
}

function DisclosureDetail({ disclosure, title }: { disclosure: Disclosure; title?: string }) {
  const { start, end_exclusive } = disclosure.locator;
  const lastLine = end_exclusive.line - 1;
  const range = start.line === end_exclusive.line
    ? `line ${start.line}, characters ${start.character}–${end_exclusive.character - 1}`
    : lastLine === start.line ? `line ${start.line}` : `lines ${start.line}–${lastLine}`;
  return (
    <p>
      {title && <strong>{title} · </strong>}
      {disclosure.interpretation}{' '}
      <span className="muted">HTML {range}</span>
    </p>
  );
}

const locatorLabels: Record<string, string> = {
  table: 'Statement table', statement_heading: 'Statement heading', metric_label: 'Metric label',
  annual_header: 'Annual period header', year_header: 'Fiscal year header', value: 'Revenue cell',
  unit_header: 'Scale disclosure', currency_symbol: 'Statement currency marker',
  currency_measure: 'Currency measure', inline_context: 'Inline XBRL context', inline_fact: 'Inline XBRL fact',
};

function revenueAmount(fact: RevenueFact) {
  const [integer, fraction] = (fact.normalized_amount ?? '').split('.');
  return fact.normalized_amount
    ? `${fact.currency} ${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction ? `.${fraction}` : ''}`
    : 'Unknown amount';
}

function RevenueDetail({ fact }: { fact: RevenueFact }) {
  const { fiscal_year: year, start, end } = fact.reporting_period;
  return (
    <details className="fact">
      <summary>FY{year} · {revenueAmount(fact)} · {fact.status === 'verified' ? 'Verified' : 'Provisional'}</summary>
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
        <DisclosureDetail key={note.id ?? note.number} disclosure={note} title={`Note ${note.number} · ${note.title}`} />
      ))}
    </details>
  );
}

function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [filings, setFilings] = useState<FilingMatch[] | null>(null);
  const [chosenAccession, setChosenAccession] = useState('');
  const [listError, setListError] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [downloadError, setDownloadError] = useState('');
  const [downloadNotice, setDownloadNotice] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [searching, setSearching] = useState(false);
  const selected = sources.find(source => source.source_id === selectedId);
  const chosenFiling = filings?.find(filing => filing.accession === chosenAccession);
  const busy = loading || uploading || downloading || searching;
  const hasCachedFiling = sources.some(source =>
    source.provenance.kind === 'sec_download' && source.accession === '0000950170-23-035122',
  );

  function openSource(source: Source) {
    setSources(current => [...current.filter(item => item.source_id !== source.source_id), source]);
    setSelectedId(source.source_id);
  }

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
      openSource(source);
      setNotice('Source saved and open for inspection.');
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : String(error));
    } finally {
      setUploading(false);
    }
  }

  async function searchFilings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    setSearching(true);
    setFilings(null);
    setChosenAccession('');
    setDownloadError('');
    setDownloadNotice('');
    try {
      const result = await secRequest<{ filings: FilingMatch[] }>('/api/filings/search', {
        company: String(fields.get('company')).trim(), year: String(fields.get('year')),
        form: String(fields.get('filingForm')),
      });
      setFilings(result.filings);
      setChosenAccession(result.filings[0]?.accession ?? '');
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : String(error));
    } finally {
      setSearching(false);
    }
  }

  async function download(filing?: FilingMatch) {
    setDownloading(true);
    setDownloadError('');
    setDownloadNotice('');
    try {
      const source = await secRequest<Source>('/api/sources/download', filing && {
        company: filing.cik, year: filing.filing_date.slice(0, 4), form: filing.form,
        accession: filing.accession,
      });
      openSource(source);
      setDownloadNotice('SEC filing open for inspection.');
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : String(error));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <main>
      <header className="masthead"><span>FRAG</span><h1>Source inspector</h1></header>
      <CollectionLookup />
      <div className="workspace">
        <aside>
          <section className="panel download" aria-labelledby="download-title">
            <h2 id="download-title">SEC EDGAR</h2>
            <form onSubmit={searchFilings} onChange={() => {
              setFilings(null);
              setDownloadError('');
              setDownloadNotice('');
            }}>
              <label>
                Company ticker or SEC CIK
                <input name="company" maxLength={20} placeholder="MSFT or 789019"
                  autoCapitalize="characters" spellCheck={false} required disabled={busy} />
              </label>
              <div className="filing-filters">
                <label>
                  Filing year
                  <input name="year" inputMode="numeric" pattern="[0-9]{4}" maxLength={4}
                    defaultValue={new Date().getFullYear()} required disabled={busy} />
                </label>
                <label>
                  SEC form
                  <input name="filingForm" list="filing-forms" defaultValue="10-K" maxLength={30}
                    autoCapitalize="characters" spellCheck={false} required disabled={busy} />
                  <datalist id="filing-forms">
                    {['10-K', '10-Q', '8-K', '20-F', '40-F', '6-K', '10-K/A', '10-Q/A'].map(form =>
                      <option key={form} value={form} />,
                    )}
                  </datalist>
                </label>
              </div>
              <button className="primary" type="submit" disabled={busy}>Find filings</button>
            </form>
            {filings?.length === 0 && <p className="muted" role="status">No matching HTML filings.</p>}
            {chosenFiling && (
              <div className="filing-results">
                <label>
                  {chosenFiling.company} filings
                  <select value={chosenAccession} onChange={event => setChosenAccession(event.target.value)}
                    disabled={busy}>
                    {filings?.map(filing => (
                      <option key={filing.accession} value={filing.accession}>
                        {filing.form} filed {filing.filing_date}
                        {filing.report_date ? ` · Period ended ${filing.report_date}` : ''} · {filing.accession}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="primary" type="button" disabled={busy} onClick={() => void download(chosenFiling)}>
                  Download selected filing
                </button>
              </div>
            )}
            <button type="button" disabled={busy} onClick={() => void download()}>
              {hasCachedFiling ? 'Open cached Microsoft FY2023 10-K' : 'Download Microsoft FY2023 10-K'}
            </button>
            {downloadError && <p className="error" role="alert">{downloadError}</p>}
            <div className="muted" role="status">
              {searching && 'Searching SEC EDGAR…'}
              {downloading && 'Retrieving the SEC filing…'}
              {!searching && !downloading && downloadNotice}
            </div>
          </section>
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
              <button className="primary" disabled={busy} type="submit">
                {uploading ? 'Preserving…' : 'Preserve source'}
              </button>
              {uploadError && <p className="error" role="alert">{uploadError}</p>}
              <div className="muted" role="status">{notice}</div>
            </form>
          </section>
          <section className="panel" aria-labelledby="sources-title">
            <div className="section-head">
              <h2 id="sources-title">Saved sources <span>({sources.length})</span></h2>
              <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh</button>
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
          <section className="panel detail empty"><h2>Inspect a source</h2><p>Download a filing, upload HTML, or select a saved source.</p></section>
        )}
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
