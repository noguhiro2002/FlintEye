import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownIcon,
  ArrowDownTrayIcon,
  ArrowPathIcon,
  ArrowUpIcon,
  CalendarDaysIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CircleStackIcon,
  PlayIcon,
  VideoCameraIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import type { ApiClient } from "../api/client";
import { EventRecordingList } from "../components/EventRecordings";
import { createRecordingThumbnailQueue, RecordingThumbnail } from "../components/RecordingThumbnail";
import type { RecordingItem } from "../types";
import { usePolling } from '../hooks/usePolling';

interface RecordingsPageProps {
  api: ApiClient;
  canDownload?: boolean;
}

type SortKey = "stream" | "recorded" | "size";
type SortDir = "asc" | "desc";
type StatusFilter = "all" | "stable" | "recording";
type PageSize = 50 | 100 | 200;

interface RecordingSection {
  key: string;
  label: string;
  items: RecordingItem[];
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx += 1;
  }
  return `${size.toFixed(1)} ${units[idx]}`;
}

function formatDateTime(unixSec: number): string {
  return new Date(unixSec * 1000).toLocaleString();
}

function formatDateHeading(unixSec: number): string {
  return new Date(unixSec * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function formatDateKey(unixSec: number): string {
  const date = new Date(unixSec * 1000);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function parseRecordedBoundary(value: string, inclusiveEnd = false): number | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value).getTime();
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return parsed / 1000 + (inclusiveEnd ? 59.999 : 0);
}

function formatDownloadTimestamp(unixSec: number): string {
  const date = new Date(unixSec * 1000);
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}_${pad(date.getHours())}-${pad(date.getMinutes())}-${pad(date.getSeconds())}`;
}

function buildDownloadFilename(item: RecordingItem): string {
  const stream = (item.stream_id || "recording").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[_\-.]+|[_\-.]+$/g, "");
  return `${stream || "recording"}_${formatDownloadTimestamp(item.modified_at)}.mp4`;
}

function formatAgeSec(ageSec: number): string {
  if (ageSec < 60) {
    return `${ageSec}s ago`;
  }
  const minutes = Math.floor(ageSec / 60);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  return `${Math.floor(minutes / 60)}h ago`;
}

function isPlaybackCachePath(relativePath: string): boolean {
  const normalized = relativePath.trim().replace(/\\/g, "/").replace(/^\/+/, "").toLowerCase();
  return normalized === ".playback_cache" || normalized.startsWith(".playback_cache/");
}

interface RecordingPaginationProps {
  position: "top" | "bottom";
  pageIndex: number;
  pageSize: PageSize;
  total: number;
  visibleCount: number;
  loading: boolean;
  onPageChange: (pageIndex: number) => void;
  onPageSizeChange: (pageSize: PageSize) => void;
}

function RecordingPagination({
  position,
  pageIndex,
  pageSize,
  total,
  visibleCount,
  loading,
  onPageChange,
  onPageSizeChange,
}: RecordingPaginationProps): JSX.Element {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const firstItem = total === 0 ? 0 : pageIndex * pageSize + 1;
  const lastItem = total === 0 ? 0 : Math.min(pageIndex * pageSize + visibleCount, total);
  const hasPrevious = pageIndex > 0;
  const hasNext = pageIndex + 1 < pageCount;

  return (
    <nav className={`recording-pagination recording-pagination-${position}`} aria-label={`${position} recording pages`}>
      <label className="recording-page-size">
        <span>Per page</span>
        <select
          value={pageSize}
          onChange={(event) => onPageSizeChange(Number(event.target.value) as PageSize)}
          disabled={loading}
        >
          <option value={50}>50</option>
          <option value={100}>100</option>
          <option value={200}>200</option>
        </select>
      </label>
      <div className="recording-page-summary" aria-live="polite">
        <strong>
          {firstItem}–{lastItem}
        </strong>
        <span>of {total}</span>
        <span className="recording-page-number">
          Page {pageIndex + 1} of {pageCount}
        </span>
      </div>
      <div className="recording-page-actions">
        <button
          type="button"
          className="icon-text-button"
          onClick={() => onPageChange(pageIndex - 1)}
          disabled={loading || !hasPrevious}
        >
          <ChevronLeftIcon aria-hidden="true" />
          Previous
        </button>
        <button
          type="button"
          className="icon-text-button"
          onClick={() => onPageChange(pageIndex + 1)}
          disabled={loading || !hasNext}
        >
          Next
          <ChevronRightIcon aria-hidden="true" />
        </button>
      </div>
    </nav>
  );
}

export function RecordingsPage({ api, canDownload = false }: RecordingsPageProps): JSX.Element {
  const [streams, setStreams] = useState<string[]>([]);
  const [selectedStream, setSelectedStream] = useState("");
  const [recordRoot, setRecordRoot] = useState("");
  const [items, setItems] = useState<RecordingItem[]>([]);
  const [total, setTotal] = useState(0);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState<PageSize>(50);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [streamError, setStreamError] = useState("");
  const [hasLoaded, setHasLoaded] = useState(false);
  const [loadedQuery, setLoadedQuery] = useState("");

  const [selectedItem, setSelectedItem] = useState<RecordingItem | null>(null);
  const [selectedVideoUrl, setSelectedVideoUrl] = useState("");
  const [preparingFileId, setPreparingFileId] = useState("");
  const [playbackOpen, setPlaybackOpen] = useState(false);
  const [playbackAudio, setPlaybackAudio] = useState<boolean | null>(null);
  const [playbackError, setPlaybackError] = useState("");
  const playbackRequestRef = useRef(0);
  const loadRequestRef = useRef(0);
  const paginationTopRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);

  const [sortKey, setSortKey] = useState<SortKey>("recorded");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [recordedFrom, setRecordedFrom] = useState("");
  const [recordedTo, setRecordedTo] = useState("");
  const [timeBasis, setTimeBasis] = useState<"recorded" | "updated">("recorded");
  const [showEvents, setShowEvents] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const timeLabel = timeBasis === "recorded" ? "Recorded" : "Updated";
  const rangeInvalid = Boolean(recordedFrom && recordedTo && recordedFrom > recordedTo);
  const queryKey = JSON.stringify([selectedStream, statusFilter, recordedFrom, recordedTo, timeBasis, sortKey, sortDir, pageIndex, pageSize]);
  const showingPrevious = hasLoaded && (loadedQuery !== queryKey || Boolean(error));
  const [thumbnailErrors, setThumbnailErrors] = useState<Record<string, boolean>>({});
  const [thumbnailQueue] = useState(createRecordingThumbnailQueue);
  const markThumbnailUnavailable = useCallback((fileId: string) => {
    setThumbnailErrors(previous => ({ ...previous, [fileId]: true }));
  }, []);

  const filteredItems = items;

  const sections = useMemo<RecordingSection[]>(() => {
    if (sortKey !== "recorded") {
      return [{ key: "all", label: "", items: filteredItems }];
    }
    const grouped = new Map<string, RecordingSection>();
    filteredItems.forEach((item) => {
      const date = timeBasis === "recorded" ? item.started_at : item.modified_at;
      const key = date == null ? "unknown" : formatDateKey(date);
      const existing = grouped.get(key);
      if (existing) {
        existing.items.push(item);
      } else {
        grouped.set(key, {
          key,
          label: date == null ? "Recording time unavailable" : formatDateHeading(date),
          items: [item],
        });
      }
    });
    return Array.from(grouped.values());
  }, [filteredItems, sortKey, timeBasis]);

  const closePlayback = (): void => {
    playbackRequestRef.current += 1;
    setPlaybackOpen(false);
    setSelectedItem(null);
    setSelectedVideoUrl("");
    setPreparingFileId("");
    setPlaybackError("");
  };

  const load = async (): Promise<void> => {
    const requestId = loadRequestRef.current + 1;
    loadRequestRef.current = requestId;
    if (rangeInvalid) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const current = (): boolean => loadRequestRef.current === requestId;
    const streamsRequest = api.getRecordingStreams().then((response) => {
      if (!current()) return;
      setStreams(response.items.filter((stream) => stream.trim().toLowerCase() !== ".playback_cache"));
      setStreamError("");
    }).catch((e: unknown) => {
      if (current()) setStreamError(`Stream filters unavailable: ${e instanceof Error ? e.message : "Request failed"}`);
    });
    const listRequest = api.getRecordings({
      streamId: selectedStream || undefined,
      status: statusFilter,
      recordedFrom: parseRecordedBoundary(recordedFrom) ?? undefined,
      recordedTo: parseRecordedBoundary(recordedTo, true) ?? undefined,
      timeBasis,
      sortBy: sortKey,
      sortDir,
      limit: pageSize,
      offset: pageIndex * pageSize,
    }).then((response) => {
      if (!current()) return;
      setRecordRoot(response.record_root);
      setTotal(response.total);
      setHasLoaded(true);
      setLoadedQuery(queryKey);
      setError("");
      const lastPageIndex = Math.max(0, Math.ceil(response.total / pageSize) - 1);
      if (pageIndex > lastPageIndex) {
        setPageIndex(lastPageIndex);
        return;
      }
      setItems(response.items.filter((item) => !isPlaybackCachePath(item.relative_path)));
      setThumbnailErrors({});
    }).catch((e: unknown) => {
      if (current()) setError(`Recordings unavailable: ${e instanceof Error ? e.message : "Request failed"}`);
    }).finally(() => {
      if (current()) setLoading(false);
    });
    await Promise.all([streamsRequest, listRequest]);
  };

  useEffect(() => {
    if (!showEvents) void load();
    return () => { loadRequestRef.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStream, statusFilter, recordedFrom, recordedTo, timeBasis, sortKey, sortDir, pageIndex, pageSize, showEvents]);

  usePolling(async () => {
    if (!showEvents && !loading && !playbackOpen && !rangeInvalid && hasLoaded) await load();
  }, 5000);

  useLayoutEffect(() => {
    if (!playbackOpen || !dialogRef.current) return undefined;
    const dialog = dialogRef.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const madeInert: Array<{ element: HTMLElement; inert: boolean }> = [];
    let node: HTMLElement | null = dialog.parentElement;
    while (node && node !== document.body) {
      const parent: HTMLElement | null = node.parentElement;
      if (!parent) break;
      for (const sibling of Array.from(parent.children)) {
        if (sibling !== node && sibling instanceof HTMLElement) {
          madeInert.push({ element: sibling, inert: sibling.inert });
          sibling.inert = true;
        }
      }
      node = parent;
    }
    const focusables = (): HTMLElement[] => Array.from(dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])'
    )).filter((element) => element.getClientRects().length > 0);
    (focusables()[0] || dialog).focus();
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        closePlayback();
      } else if (event.key === "Tab") {
        const elements = focusables();
        const first = elements[0] || dialog;
        const last = elements[elements.length - 1] || dialog;
        if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
          event.preventDefault(); first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      madeInert.forEach(({ element, inert }) => { element.inert = inert; });
      window.removeEventListener("keydown", onKeyDown);
      triggerRef.current?.focus();
      triggerRef.current = null;
    };
  }, [playbackOpen]);

  const playRecording = async (item: RecordingItem): Promise<void> => {
    if (!item.is_stable) {
      return;
    }
    if (!playbackOpen) triggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const requestId = playbackRequestRef.current + 1;
    playbackRequestRef.current = requestId;
    setSelectedItem(item);
    setSelectedVideoUrl("");
    setPlaybackError("");
    setPlaybackAudio(null);
    setPreparingFileId(item.file_id);
    setPlaybackOpen(true);
    try {
      const prepared = await api.prepareRecordingPlayback(item.file_id);
      if (playbackRequestRef.current !== requestId) {
        return;
      }
      setPlaybackAudio(prepared.has_audio ?? null);
      setSelectedVideoUrl(api.getRecordingPlayableUrl(item.file_id));
    } catch (e) {
      if (playbackRequestRef.current === requestId) {
        setPlaybackError(e instanceof Error ? e.message : "Failed to prepare recording playback");
      }
    } finally {
      if (playbackRequestRef.current === requestId) {
        setPreparingFileId("");
      }
    }
  };

  const directionLabel =
    sortKey === "stream"
      ? sortDir === "asc"
        ? "A–Z"
        : "Z–A"
      : sortKey === "recorded"
      ? sortDir === "desc"
        ? "Newest"
        : "Oldest"
      : sortDir === "desc"
        ? "Largest"
        : "Smallest";

  const scrollToFirstPageControl = (): void => {
    paginationTopRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const goToPage = (nextPageIndex: number): void => {
    const pageCount = Math.max(1, Math.ceil(total / pageSize));
    const boundedPageIndex = Math.max(0, Math.min(nextPageIndex, pageCount - 1));
    if (boundedPageIndex === pageIndex) {
      return;
    }
    closePlayback();
    setPageIndex(boundedPageIndex);
    scrollToFirstPageControl();
  };

  const changePageSize = (nextPageSize: PageSize): void => {
    closePlayback();
    setPageSize(nextPageSize);
    setPageIndex(0);
    scrollToFirstPageControl();
  };

  return (
    <div className="page recordings-page">
      <div className="page-header">
        <div>
          <h2>Recordings</h2>
          <p className="panel-note">Times shown in {Intl.DateTimeFormat().resolvedOptions().timeZone}.</p>
          {!showEvents && <div className="recording-root" title={recordRoot}>
            {recordRoot || "Recording root unavailable"}
          </div>}
        </div>
        {!showEvents && <button type="button" className="icon-text-button" onClick={() => void load()} disabled={loading}>
          <ArrowPathIcon aria-hidden="true" />
          {loading ? "Refreshing..." : "Refresh"}
        </button>}
      </div>
      <nav className="button-row recording-view-switch" aria-label="Recording views">
        <button type="button" aria-pressed={!showEvents} onClick={() => setShowEvents(false)}>Loop recordings</button>
        <button type="button" aria-pressed={showEvents} onClick={() => { setShowEvents(true); setError(""); }}>Event recordings</button>
      </nav>

      {error && <div className="panel-error" role="alert">{error}</div>}
      {showEvents ? <EventRecordingList api={api} canDownload={canDownload}
        onPlay={item => void playRecording(item)} busy={Boolean(preparingFileId)} /> : <>
      {streamError && <div className="panel-error" role="alert">{streamError}</div>}
      {showingPrevious && <div role="status">Showing previous results; they may not match the current filters.</div>}

      <button type="button" className="recording-filter-toggle" aria-expanded={mobileFiltersOpen}
        aria-controls="recording-toolbar" onClick={() => setMobileFiltersOpen(open => !open)}>
        {mobileFiltersOpen ? "Hide filters and sorting" : "Show filters and sorting"}
      </button>
      <section id="recording-toolbar" className={"recording-toolbar" + (mobileFiltersOpen ? " is-open" : "")} aria-label="Recording filters and sorting">
        <div className="recording-toolbar-group recording-filter-group" aria-label="Filters">
          <div className="recording-toolbar-group-title">Filters</div>
          <div className="recording-filter-controls">
            <label>
              <span>Stream</span>
              <select
                value={selectedStream}
                onChange={(event) => {
                  setSelectedStream(event.target.value);
                  setPageIndex(0);
                  closePlayback();
                  setError("");
                }}
              >
                <option value="">All Streams</option>
                {streams.map((stream) => (
                  <option key={stream} value={stream}>
                    {stream}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Status</span>
              <select
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(event.target.value as StatusFilter);
                  setPageIndex(0);
                }}
              >
                <option value="all">All Statuses</option>
                <option value="stable">Stable</option>
                <option value="recording">Recording</option>
              </select>
            </label>
            <label>
              <span>Date basis</span>
              <select aria-label="Date basis" value={timeBasis} onChange={event => {
                setTimeBasis(event.target.value as "recorded" | "updated");
                setPageIndex(0);
              }}>
                <option value="recorded">Recording time</option>
                <option value="updated">File update time</option>
              </select>
            </label>
            <label>
              <span>{timeLabel} from</span>
              <input
                type="datetime-local"
                step="60"
                value={recordedFrom}
                max={recordedTo || undefined}
                aria-invalid={rangeInvalid}
                aria-describedby={rangeInvalid ? "recording-range-error" : undefined}
                onInput={(event) => {
                  setRecordedFrom(event.currentTarget.value);
                  setPageIndex(0);
                }}
              />
            </label>
            <label>
              <span>{timeLabel} to</span>
              <input
                type="datetime-local"
                step="60"
                value={recordedTo}
                min={recordedFrom || undefined}
                aria-invalid={rangeInvalid}
                aria-describedby={rangeInvalid ? "recording-range-error" : undefined}
                onInput={(event) => {
                  setRecordedTo(event.currentTarget.value);
                  setPageIndex(0);
                }}
              />
            </label>
          </div>
          {rangeInvalid && <div id="recording-range-error" className="panel-error" role="alert">The start date must be before the end date.</div>}
        </div>

        <div className="recording-toolbar-group recording-sort-group" aria-label="Sort recordings">
          <div className="recording-toolbar-group-title">Sort</div>
          <div className="recording-sort-controls">
            <label>
              <span>Field</span>
              <select
                aria-label="Sort field"
                value={sortKey}
                onChange={(event) => {
                  const nextKey = event.target.value as SortKey;
                  setSortKey(nextKey);
                  setSortDir(nextKey === "stream" ? "asc" : "desc");
                  setPageIndex(0);
                }}
              >
                <option value="stream">Stream</option>
                <option value="recorded">{timeLabel} date</option>
                <option value="size">Size</option>
              </select>
            </label>
            <button
              type="button"
              className="recording-sort-direction"
              onClick={() => {
                setSortDir((previous) => (previous === "asc" ? "desc" : "asc"));
                setPageIndex(0);
              }}
              title={`Sort ${directionLabel.toLowerCase()}`}
            >
              {sortDir === "desc" ? <ArrowDownIcon aria-hidden="true" /> : <ArrowUpIcon aria-hidden="true" />}
              <span>{directionLabel}</span>
            </button>
          </div>
        </div>
        <div className="recording-result-count" aria-live="polite">
          {hasLoaded ? `${total} ${total === 1 ? "recording" : "recordings"}` : loading ? "Loading recordings..." : ""}
        </div>
      </section>

      <div ref={paginationTopRef}>
        {hasLoaded && total > 0 && <RecordingPagination
          position="top"
          pageIndex={pageIndex}
          pageSize={pageSize}
          total={total}
          visibleCount={items.length}
          loading={loading}
          onPageChange={goToPage}
          onPageSizeChange={changePageSize}
        />}
      </div>

      <div className="recording-library">
        {filteredItems.length === 0 ? (
          rangeInvalid ? null : loading ? <div className="panel-empty">Loading recordings...</div> : error ? null : hasLoaded ? <div className="panel-empty">No recordings match the current filters.</div> : null
        ) : (
          sections.map((section) => (
            <section key={section.key} className="recording-day-group">
              {section.label && <h3>{section.label}</h3>}
              <div className="recording-grid">
                {section.items.map((item) => {
                  const unavailable = Boolean(thumbnailErrors[item.file_id]);
                  const statusText = item.is_stable ? (item.completion_state === "recovered" ? "Recovered" : "Stable")
                    : item.completion_state === "unavailable" ? "Completion unavailable" : `Recording / finalizing · ${formatAgeSec(item.age_sec)}`;
                  const downloadFilename = buildDownloadFilename(item);
                  return (
                    <article key={item.file_id} className="recording-card">
                      <button
                        type="button"
                        className="recording-thumbnail"
                        onClick={() => void playRecording(item)}
                        disabled={!item.is_stable || Boolean(preparingFileId)}
                        aria-label={item.is_stable ? `Play ${item.relative_path}` : `${item.relative_path} is recording`}
                      >
                        {unavailable ? (
                          <span className="recording-thumbnail-empty">
                            <VideoCameraIcon aria-hidden="true" />
                            Preview unavailable
                          </span>
                        ) : (
                          <RecordingThumbnail
                            key={item.modified_at}
                            fileId={item.file_id}
                            url={api.getRecordingThumbnailUrl(item.file_id, item.modified_at)}
                            alt={`Recorded preview for ${item.stream_id || item.relative_path}`}
                            paused={playbackOpen}
                            enqueue={thumbnailQueue}
                            onError={markThumbnailUnavailable}
                          />
                        )}
                        {item.is_stable && (
                          <span className="recording-thumbnail-play" aria-hidden="true">
                            <PlayIcon />
                          </span>
                        )}
                      </button>

                      <div className="recording-card-content">
                        <div className="recording-card-heading">
                          <strong title={item.relative_path}>{item.stream_id || "Unknown stream"}</strong>
                          <span className={item.is_stable ? "status-badge ok" : "status-badge ng"}>{statusText}</span>
                        </div>
                        <div className="recording-card-meta">
                          <span>Start: {item.started_at != null ? formatDateTime(item.started_at) : 'Unknown'}</span>
                          <span>End: {item.ended_at != null ? formatDateTime(item.ended_at) : 'Unknown'}</span>
                          <span>Length: {item.duration_sec != null ? `${item.duration_sec.toFixed(1)} s` : 'Unknown'}</span>
                          <span>
                            <CalendarDaysIcon aria-hidden="true" />
                            <span className="recording-meta-label">Updated</span>
                            {formatDateTime(item.modified_at)}
                          </span>
                          <span>
                            <CircleStackIcon aria-hidden="true" />
                            <span className="recording-meta-label">Size</span>
                            {formatBytes(item.size_bytes)}
                          </span>
                        </div>
                        <div className="recording-card-actions">
                          <button
                            type="button"
                            className="icon-text-button"
                            aria-label={item.is_stable ? `Play ${item.stream_id || item.relative_path}, ${formatDateTime(item.modified_at)}` : `${item.relative_path} is recording`}
                            onClick={() => void playRecording(item)}
                            disabled={!item.is_stable || Boolean(preparingFileId)}
                          >
                            <PlayIcon aria-hidden="true" />
                            {preparingFileId === item.file_id ? "Preparing..." : item.is_stable ? "Play" : "Wait"}
                          </button>
                          {canDownload && item.is_stable && (
                            <a
                              className="icon-only-button"
                              href={api.getRecordingFileUrl(item.file_id)}
                              download={downloadFilename}
                              title={`Download ${downloadFilename}`}
                              aria-label={`Download ${downloadFilename}`}
                            >
                              <ArrowDownTrayIcon aria-hidden="true" />
                            </a>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          ))
        )}
      </div>

      {hasLoaded && total > pageSize && <RecordingPagination
        position="bottom"
        pageIndex={pageIndex}
        pageSize={pageSize}
        total={total}
        visibleCount={items.length}
        loading={loading}
        onPageChange={goToPage}
        onPageSizeChange={changePageSize}
      />}
      </>}

      {playbackOpen && selectedItem && (
        <div className="recording-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && closePlayback()}>
          <section ref={dialogRef} tabIndex={-1} className="recording-modal" role="dialog" aria-modal="true" aria-labelledby="recording-modal-title">
            <header className="recording-modal-header">
              <div>
                <h3 id="recording-modal-title">{selectedItem.stream_id || "Recording"}</h3>
                <div className="recording-modal-summary">
                  <span>{formatDateTime(selectedItem.modified_at)}</span>
                  <span>{formatBytes(selectedItem.size_bytes)}</span>
                  <span className="status-badge ok">Stable</span>
                </div>
              </div>
              <button type="button" className="icon-only-button" onClick={closePlayback} aria-label="Close player">
                <XMarkIcon aria-hidden="true" />
              </button>
            </header>

            <div className="recording-modal-player">
              {preparingFileId ? (
                <div className="recording-modal-loading">
                  <ArrowPathIcon aria-hidden="true" />
                  Preparing playback-friendly video...
                </div>
              ) : playbackError ? (
                <div className="recording-modal-error">
                  <div>{playbackError}</div>
                  <button type="button" onClick={() => void playRecording(selectedItem)}>
                    Try again
                  </button>
                </div>
              ) : (
                <video
                  key={selectedItem.file_id}
                  className="recording-video"
                  controls
                  autoPlay
                  crossOrigin="use-credentials"
                  preload="metadata"
                  src={selectedVideoUrl}
                  onError={() => setPlaybackError("Failed to stream recording file")}
                />
              )}
            </div>

            <footer className="recording-modal-footer">
              {playbackAudio !== null && <span>{playbackAudio ? "Audio included" : "Video only"}</span>}
              <div className="recording-modal-path" title={selectedItem.relative_path}>
                <span>Path</span>
                {selectedItem.relative_path}
              </div>
              {canDownload && (
                <a
                  className="icon-text-button"
                  href={api.getRecordingFileUrl(selectedItem.file_id)}
                  download={buildDownloadFilename(selectedItem)}
                  title={`Download ${buildDownloadFilename(selectedItem)}`}
                >
                  <ArrowDownTrayIcon aria-hidden="true" />
                  Download
                </a>
              )}
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
