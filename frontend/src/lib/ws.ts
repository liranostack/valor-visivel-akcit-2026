// WebSocket client for the ApiStack: queues messages until open, reconnects with backoff.
import {
  encodeClientMessage,
  parseServerEvent,
  type ClientMessage,
  type ServerEvent,
} from "./protocol";
import { createMockServer } from "./mock";

export type ConnectionStatus = "connecting" | "open" | "closed" | "rejected";

/** The access code travels in the query string; $connect checks it (A.04.10). */
export function withAccessCode(url: string, code: string): string {
  const clean = code.trim();
  if (!clean) return url;
  return `${url}${url.includes("?") ? "&" : "?"}code=${encodeURIComponent(clean)}`;
}

export interface Connection {
  send(msg: ClientMessage): void;
  close(): void;
}

export interface ConnectionOptions {
  url?: string;
  mock?: boolean;
  onEvent: (event: ServerEvent) => void;
  onStatus?: (status: ConnectionStatus) => void;
  socketFactory?: (url: string) => WebSocket;
  maxRetries?: number;
}

export function connect(options: ConnectionOptions): Connection {
  if (options.mock || !options.url) return createMockServer(options.onEvent);
  return new LiveConnection(options);
}

class LiveConnection implements Connection {
  private socket: WebSocket | null = null;
  private queue: string[] = [];
  private retries = 0;
  private closedByUser = false;
  private everOpened = false;

  constructor(private readonly options: ConnectionOptions) {
    this.open();
  }

  send(msg: ClientMessage): void {
    const data = encodeClientMessage(msg);
    if (this.socket?.readyState === 1) this.socket.send(data);
    else this.queue.push(data);
  }

  close(): void {
    this.closedByUser = true;
    this.socket?.close();
  }

  private open(): void {
    const { url, onEvent, onStatus, socketFactory } = this.options;
    onStatus?.("connecting");
    const socket = (socketFactory ?? ((u: string) => new WebSocket(u)))(
      url as string,
    );
    this.socket = socket;
    socket.onopen = () => {
      this.retries = 0;
      this.everOpened = true;
      onStatus?.("open");
      for (const data of this.queue.splice(0)) socket.send(data);
    };
    socket.onmessage = (message: MessageEvent) => {
      const event = parseServerEvent(String(message.data));
      if (event) onEvent(event);
    };
    socket.onclose = () => {
      if (!this.everOpened && !this.closedByUser) {
        // The first handshake failed: API Gateway refused it (wrong access code) or the
        // server is unreachable. Retrying would only repeat the refusal.
        onStatus?.("rejected");
        return;
      }
      onStatus?.("closed");
      if (this.closedByUser) return;
      if (this.retries >= (this.options.maxRetries ?? 5)) return;
      const delay = Math.min(1000 * 2 ** this.retries, 8000);
      this.retries += 1;
      setTimeout(() => this.open(), delay);
    };
  }
}
