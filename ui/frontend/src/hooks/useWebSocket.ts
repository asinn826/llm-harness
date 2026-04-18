/** WebSocket hook for streaming chat and comparison. */

import { useCallback, useEffect, useRef, useState } from "react";
import type { WSServerMessage, WSClientMessage } from "../lib/types";

type ConnectionState = "connecting" | "open" | "closed" | "error";

interface UseWebSocketOptions {
  /** WebSocket path, e.g. "/ws/chat" */
  path: string;
  /** Called for every server message */
  onMessage: (msg: WSServerMessage) => void;
  /** Auto-connect on mount (default: true) */
  autoConnect?: boolean;
}

export function useWebSocket({ path, onMessage, autoConnect = true }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const [state, setState] = useState<ConnectionState>("closed");

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}${path}`;
    const ws = new WebSocket(url);

    setState("connecting");

    ws.onopen = () => setState("open");
    ws.onclose = () => {
      setState("closed");
      wsRef.current = null;
    };
    ws.onerror = () => setState("error");
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSServerMessage;
        onMessageRef.current(msg);
      } catch {
        // ignore malformed messages
      }
    };

    wsRef.current = ws;
  }, [path]);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const send = useCallback((msg: WSClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  useEffect(() => {
    if (autoConnect) connect();
    return disconnect;
  }, [autoConnect, connect, disconnect]);

  return { state, connect, disconnect, send };
}
