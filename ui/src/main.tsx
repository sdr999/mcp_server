import React, { Component, ErrorInfo, ReactNode } from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.tsx';
import './index.css';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error in React render:', error, errorInfo);
    this.setState({ error, errorInfo });
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: '100vh',
          backgroundColor: '#070a10',
          color: '#f87171',
          padding: '2rem',
          fontFamily: 'monospace',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '1rem'
        }}>
          <h2 style={{ color: '#ff9f1c', margin: 0 }}>⚠️ ORBITAL COMMAND RENDER ANOMALY</h2>
          <p style={{ color: '#94a3b8', margin: 0 }}>An error occurred during UI rendering:</p>
          <pre style={{
            background: '#0d131f',
            border: '1px solid #e11d48',
            padding: '1rem',
            borderRadius: '0.375rem',
            maxWidth: '50rem',
            overflow: 'auto',
            color: '#fb7185'
          }}>
            {this.state.error?.toString()}
          </pre>
          <button
            onClick={() => {
              localStorage.removeItem('mcp_token');
              window.location.reload();
            }}
            style={{
              background: '#0284c7',
              border: '1px solid #38bdf8',
              color: '#ffffff',
              padding: '0.6rem 1.25rem',
              borderRadius: '0.375rem',
              cursor: 'pointer',
              fontWeight: 'bold'
            }}
          >
            🔄 Reset Cache & Reload
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
