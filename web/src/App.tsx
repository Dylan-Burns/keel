import type {JSX} from 'react';
import {useCallback, useState} from 'react';

import {fetchChunk} from './api/client';
import {AnswerArea} from './components/AnswerArea';
import {CoverageSummary} from './components/CoverageSummary';
import {Footer} from './components/Footer';
import {IndexNotBuiltCard} from './components/IndexNotBuiltCard';
import {OfflineBanner} from './components/OfflineBanner';
import {OutOfScopeCard} from './components/OutOfScopeCard';
import {PartialCoverageBanner} from './components/PartialCoverageBanner';
import {ProviderDownBanner} from './components/ProviderDownBanner';
import {QuestionArea} from './components/QuestionArea';
import {RateLimitedCard} from './components/RateLimitedCard';
import type {SelectedChunk} from './components/RightPanel';
import {RightPanel} from './components/RightPanel';
import {StaleIndexBanner} from './components/StaleIndexBanner';
import {TokenField} from './components/TokenField';
import {TopBar} from './components/TopBar';
import {answerToJson, answerToMarkdown} from './lib/answerExport';
import type {Example} from './lib/examples';
import {EXAMPLES} from './lib/examples';
import {baseState, canAsk, currentRun, hasOverlay, health} from './state';
import {useKeel} from './useKeel';

/**
 * Saves a text as a file through a temporary link.
 *
 * @param name The file name.
 * @param text The content.
 */
function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], {type: 'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * The Keel page: the regions of chapter 14.5 and the states of 14.6.
 *
 * @return The page.
 */
export function App(): JSX.Element {
  const {state, hasToken, ask, saveToken, reload} = useKeel();
  const [question, setQuestion] = useState('');
  const [selected, setSelected] = useState<SelectedChunk | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  const ui = state.ui;
  const base = baseState(ui);
  const run = currentRun(ui);
  const askEnabled = canAsk(ui);
  const meta = run?.final?.meta ?? null;
  const indexVersion =
    meta?.index_version ??
    run?.meta?.index_version ??
    state.service.ready?.index_version ??
    null;

  const onAsk = useCallback(
    (text: string): void => {
      setSelected(null);
      setCopyStatus(null);
      ask(text);
    },
    [ask],
  );
  const onPick = (example: Example): void => {
    setQuestion(example.question);
    onAsk(example.question);
  };
  const onSelectCitation = useCallback((chunkId: string): void => {
    setSelected({chunkId, detail: null, error: null});
    setPanelOpen(true);
    fetchChunk(chunkId)
      .then(detail =>
        setSelected(current =>
          current?.chunkId === chunkId
            ? {chunkId, detail, error: null}
            : current,
        ),
      )
      .catch(() =>
        setSelected(current =>
          current?.chunkId === chunkId
            ? {
                chunkId,
                detail: null,
                error: 'The chunk text could not be loaded.',
              }
            : current,
        ),
      );
  }, []);
  const onCopy = (): void => {
    if (run === null) {
      return;
    }
    navigator.clipboard
      .writeText(answerToMarkdown(run))
      .then(() =>
        setCopyStatus(
          run.final === null ? 'Copied a partial answer' : 'Copied',
        ),
      )
      .catch(() => setCopyStatus('Copy failed'));
  };
  const onExport = (): void => {
    if (run !== null) {
      download(
        `keel-${run.meta?.request_id ?? run.requestId}.json`,
        answerToJson(run),
      );
    }
  };

  if (base.kind === 'index_not_built') {
    return (
      <div
        className="min-h-screen bg-paper font-sans text-ink"
        data-state={base.kind}
      >
        <TopBar
          indexVersion={indexVersion}
          health={health(state)}
          lastMeta={null}
        />
        <IndexNotBuiltCard onRecheck={reload} />
      </div>
    );
  }

  const showAnswer =
    run !== null &&
    base.kind !== 'out_of_scope' &&
    (base.kind !== 'rate_limited' || run.final !== null);

  return (
    <div
      className="flex min-h-screen flex-col bg-paper font-sans text-ink"
      data-state={base.kind}
    >
      <TopBar
        indexVersion={indexVersion}
        health={health(state)}
        lastMeta={meta}
      >
        <TokenField
          hasToken={hasToken}
          rejected={state.service.tokenRejected}
          onSave={saveToken}
        />
      </TopBar>
      {hasOverlay(ui, 'network_offline') && <OfflineBanner />}
      {hasOverlay(ui, 'stale_index') && (
        <StaleIndexBanner
          warnings={state.service.indexStatus?.warnings ?? []}
        />
      )}
      <div className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 px-4 py-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <main className="min-w-0 space-y-4">
          <QuestionArea
            question={question}
            onQuestionChange={setQuestion}
            onAsk={onAsk}
            askEnabled={askEnabled}
            examples={EXAMPLES}
            analysis={run?.analysis ?? null}
          />
          {base.kind === 'empty' && (
            <CoverageSummary
              coverage={state.service.coverage}
              hasToken={hasToken}
            />
          )}
          {base.kind === 'partial_coverage' && (
            <PartialCoverageBanner
              companiesMissing={base.companiesMissing}
              unverifiedFindings={base.unverifiedFindings}
            />
          )}
          {base.kind === 'provider_down' && (
            <ProviderDownBanner
              message={base.message}
              retryEnabled={askEnabled}
              onRetry={
                base.run === null ? null : () => onAsk(base.run?.question ?? '')
              }
            />
          )}
          {base.kind === 'rate_limited' && (
            <RateLimitedCard secondsLeft={base.secondsLeft} />
          )}
          {base.kind === 'out_of_scope' && (
            <OutOfScopeCard
              reason={base.reason}
              coverage={state.service.coverage}
              examples={EXAMPLES}
              askEnabled={askEnabled}
              onPick={onPick}
            />
          )}
          {showAnswer && run !== null && (
            <AnswerArea
              run={run}
              streaming={base.kind === 'streaming'}
              askEnabled={askEnabled}
              onSelectCitation={onSelectCitation}
              onAsk={text => {
                setQuestion(text);
                onAsk(text);
              }}
            />
          )}
          {run?.retrieval !== undefined && run?.retrieval !== null && (
            <button
              type="button"
              className="rounded border border-slate-300 bg-white px-3 py-1 text-sm lg:hidden"
              data-testid="open-sources"
              onClick={() => setPanelOpen(true)}
            >
              Sources
            </button>
          )}
        </main>
        <RightPanel
          run={run}
          selected={selected}
          open={panelOpen}
          onClose={() => setPanelOpen(false)}
        />
      </div>
      <Footer
        requestId={run?.meta?.request_id ?? run?.final?.request_id ?? null}
        promptVersion={
          meta?.prompt_version ?? run?.meta?.prompt_version ?? null
        }
        hasAnswer={
          run !== null && (run.deltas.length > 0 || run.final !== null)
        }
        copyStatus={copyStatus}
        onCopy={onCopy}
        onExport={onExport}
      />
    </div>
  );
}
