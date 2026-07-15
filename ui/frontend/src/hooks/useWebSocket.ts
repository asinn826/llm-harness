/** WebSocket hook for streaming chat and comparison. */

import { useCallback, useEffect, useRef, useState } from "react";
import type { WSServerMessage, WSClientMessage } from "../lib/types";
import { wsUrl } from "../lib/api";

type ConnectionState = "connecting" | "open" | "closed" | "error";

interface UseWebSocketOptions {
  /** WebSocket path, e.g. "/ws/chat" */
  path: string;
  /** Called for every server message */
  onMessage: (msg: WSServerMessage) => void;
  /** Auto-connect on mount (default: true) */
  autoConnect?: boolean;
  /** Called when an established connection drops while reconnecting. */
  onDisconnect?: () => void;
}

const RECONNECT_DELAY = 1000;
const MAX_RECONNECT_DELAY = 10000;

export function useWebSocket({
  path,
  onMessage,
  autoConnect = true,
  onDisconnect,
}: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  const onDisconnectRef = useRef(onDisconnect);

  const [state, setState] = useState<ConnectionState>("closed");
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelay = useRef(RECONNECT_DELAY);
  const shouldReconnect = useRef(true);
  const connectRef = useRef<() => void>(() => {});

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    onDisconnectRef.current = onDisconnect;
  }, [onDisconnect]);

  const connect = useCallback(() => {
    // Don't connect if already open or connecting
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    const url = wsUrl(path);

    setState("connecting");

    try {
      const ws = new WebSocket(url);
      let didOpen = false;

      ws.onopen = () => {
        didOpen = true;
        setState("open");
        reconnectDelay.current = RECONNECT_DELAY; // reset on successful connect
      };

      ws.onclose = () => {
        setState("closed");
        wsRef.current = null;
        // Auto-reconnect
        if (shouldReconnect.current) {
          if (didOpen) onDisconnectRef.current?.();
          reconnectTimer.current = setTimeout(() => {
            connectRef.current();
          }, reconnectDelay.current);
          // Exponential backoff, capped
          reconnectDelay.current = Math.min(
            reconnectDelay.current * 1.5,
            MAX_RECONNECT_DELAY
          );
        }
      };

      ws.onerror = () => {
        setState("error");
        // onclose will fire after onerror, which triggers reconnect
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as WSServerMessage;
          onMessageRef.current(msg);
        } catch {
          // ignore malformed messages
        }
      };

      wsRef.current = ws;
    } catch {
      setState("error");
    }
  }, [path]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const disconnect = useCallback(() => {
    shouldReconnect.current = false;
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const send = useCallback((msg: WSClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  useEffect(() => {
    let active = true;
    if (autoConnect) {
      shouldReconnect.current = true;
      queueMicrotask(() => {
        if (active) connect();
      });
    }
    return () => {
      active = false;
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return { state, connect, disconnect, send };
}
