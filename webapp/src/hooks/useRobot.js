import { useCallback, useRef, useState } from 'react';
import { REQUEST_TIMEOUT_MS, STREAM_PORT } from '../constants/commands';

/**
 * Transport layer: turns a command id into a GET against the robot, and tracks
 * whether the robot is answering.
 *
 * @param {string} ip - robot address, e.g. "192.168.4.1"
 * @returns {{ send: (cmd: string) => void, streamUrl: string, link: 'unknown'|'connected'|'offline' }}
 */
export function useRobot(ip) {
  const [link, setLink] = useState('unknown');

  // `send` is handed to event listeners that we register once. Reading the IP
  // through a ref keeps `send` referentially stable, so those listeners never
  // need re-registering and can never capture a stale address.
  const ipRef = useRef(ip);
  ipRef.current = ip;

  const send = useCallback((cmd) => {
    const origin = `http://${ipRef.current.trim()}`;
    const request = new XMLHttpRequest();

    // A fresh XHR per command: reusing one object would abort whatever is still
    // in flight, and an aborted /stop is the one failure we cannot tolerate.
    request.open('GET', `${origin}/${cmd}?${Date.now()}`, true);
    request.timeout = REQUEST_TIMEOUT_MS;
    request.onload = () => setLink('connected');
    request.onerror = () => setLink('offline');
    request.ontimeout = () => setLink('offline');
    request.send();
  }, []);

  const streamUrl = `http://${ip.trim()}:${STREAM_PORT}/stream`;

  return { send, streamUrl, link };
}
