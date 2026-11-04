import { Component } from 'react';
import { Card } from './ui';

/** A crash in one page must not blank the whole app: show it, and let people carry on. */
export default class ErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error('Nigrani UI error', error, info?.componentStack); } // eslint-disable-line no-console
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Card title="Something went wrong on this page">
        <p className="muted" style={{ marginTop: 0 }}>The rest of Nigrani still works. You can try again, or go back to the overview.</p>
        <pre className="mono err" style={{ whiteSpace: 'pre-wrap', margin: '0 0 12px' }}>{String(this.state.error?.message || this.state.error)}</pre>
        <div className="row">
          <button className="btn primary" onClick={() => this.setState({ error: null })}>Try again</button>
          <a className="btn" href="#/overview">Go to overview</a>
        </div>
      </Card>
    );
  }
}
