import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown, Send } from 'lucide-react';

interface FeedbackBarProps {
  messageId: string;
  query: string;
  response: string;
  pipelineType?: string;
}

export default function FeedbackBar({ messageId, query, response, pipelineType }: FeedbackBarProps) {
  const [vote, setVote] = useState<'up' | 'down' | null>(null);
  const [issueOpen, setIssueOpen] = useState(false);
  const [issueText, setIssueText] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submitFeedback = async (v: 1 | -1, issue?: string) => {
    setSubmitting(true);
    try {
      await fetch('/api/feedback', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message_id: messageId,
          query_text: query,
          response_text: response,
          pipeline_type: pipelineType,
          vote: v,
          issue_description: issue || undefined,
        }),
      });
    } catch {
      /* silent fail for prototype */
    }
    setSubmitting(false);
  };

  const handleUp = () => {
    if (vote) return;
    setVote('up');
    submitFeedback(1);
  };

  const handleDown = () => {
    if (vote) return;
    setVote('down');
    setIssueOpen(true);
  };

  const handleIssueSend = () => {
    submitFeedback(-1, issueText);
    setIssueOpen(false);
  };

  return (
    <div className="feedback-bar">
      <button
        className={`feedback-btn ${vote === 'up' ? 'active-up' : ''}`}
        onClick={handleUp}
        disabled={!!vote || submitting}
        title="有帮助"
      >
        <ThumbsUp size={14} />
      </button>
      <button
        className={`feedback-btn ${vote === 'down' ? 'active-down' : ''}`}
        onClick={handleDown}
        disabled={!!vote || submitting}
        title="需改进"
      >
        <ThumbsDown size={14} />
      </button>

      {issueOpen && (
        <div className="feedback-issue">
          <input
            type="text"
            value={issueText}
            onChange={e => setIssueText(e.target.value)}
            placeholder="描述问题 (可选)..."
            className="feedback-issue-input"
            onKeyDown={e => e.key === 'Enter' && handleIssueSend()}
          />
          <button className="feedback-issue-send" onClick={handleIssueSend}>
            <Send size={12} />
          </button>
        </div>
      )}
    </div>
  );
}
