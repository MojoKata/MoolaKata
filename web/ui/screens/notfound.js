import { html } from '../app/html.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';

export default function NotFound() {
  useTitle('Not Found');
  useGuide('dashboard');
  return html`
    <div class="card">
      <p>There is nothing here. <a href="/ui/">Back to the Dashboard</a></p>
    </div>
  `;
}
