"""Tests for OpenTelemetry tracing (v15.0)."""
import unittest


class TestSetupTracing(unittest.TestCase):
    def test_setup_does_not_raise(self):
        from data_agent.otel_tracing import setup_otel_tracing
        setup_otel_tracing()  # Should not raise even without exporter

    def test_get_tracer_returns_something(self):
        from data_agent.otel_tracing import setup_otel_tracing, get_tracer
        setup_otel_tracing()
        tracer = get_tracer()
        # May be None if OTel not configured, or a Tracer instance
        # Just verify no crash
        self.assertTrue(tracer is None or hasattr(tracer, 'start_as_current_span'))


class TestTraceContextManagers(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_span_noop(self):
        """Without exporter, context manager should still work as no-op."""
        from data_agent.otel_tracing import trace_pipeline_run
        async with trace_pipeline_run("general", "test", "abc123") as ctx:
            self.assertIsInstance(ctx, dict)

    async def test_agent_span_noop(self):
        from data_agent.otel_tracing import trace_agent_run
        async with trace_agent_run("test_agent", "general") as ctx:
            self.assertIsInstance(ctx, dict)

    async def test_tool_span_noop(self):
        from data_agent.otel_tracing import trace_tool_call
        async with trace_tool_call("describe_geodataframe", "explorer", ["file_path"]) as ctx:
            self.assertIsInstance(ctx, dict)

    async def test_llm_span_noop(self):
        from data_agent.otel_tracing import trace_llm_call
        async with trace_llm_call("planner", "gemini-2.5-flash") as ctx:
            self.assertIsInstance(ctx, dict)

    async def test_nested_spans(self):
        """Test nested context managers don't crash."""
        from data_agent.otel_tracing import trace_pipeline_run, trace_agent_run, trace_tool_call
        async with trace_pipeline_run("optimization", "test", "xyz"):
            async with trace_agent_run("explorer", "optimization"):
                async with trace_tool_call("describe_geodataframe", "explorer"):
                    pass  # Should not raise


class TestTwmTraceContextManager(unittest.TestCase):
    def test_twm_operation_span_noop(self):
        from data_agent.otel_tracing import trace_twm_operation

        with trace_twm_operation(
            "counterfactual_rollout",
            state_version_id="state-1",
            backend="torch_spatiotemporal_transformer",
            sample_count=12,
            gate_status="review",
        ) as ctx:
            self.assertIsInstance(ctx, dict)

    def test_twm_operation_span_sets_attributes(self):
        import data_agent.otel_tracing as otel

        class FakeSpan:
            def __init__(self):
                self.attributes = {}

            def set_attribute(self, key, value):
                self.attributes[key] = value

        class FakeSpanContext:
            def __init__(self, span):
                self.span = span

            def __enter__(self):
                return self.span

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeTracer:
            def __init__(self):
                self.started = []
                self.span = FakeSpan()

            def start_as_current_span(self, name, attributes=None):
                self.started.append((name, dict(attributes or {})))
                return FakeSpanContext(self.span)

        old_tracer = otel._tracer
        fake = FakeTracer()
        otel._tracer = fake
        try:
            with otel.trace_twm_operation(
                "train_dynamics_candidate",
                state_version_id="state-2",
                backend="torch_hierarchical_graph",
                sample_count=34,
                gate_status="pass",
            ):
                pass
        finally:
            otel._tracer = old_tracer

        self.assertEqual(fake.started[0][0], "twm:train_dynamics_candidate")
        attrs = fake.started[0][1]
        self.assertEqual(attrs["twm.operation"], "train_dynamics_candidate")
        self.assertEqual(attrs["twm.state_version_id"], "state-2")
        self.assertEqual(attrs["twm.backend"], "torch_hierarchical_graph")
        self.assertEqual(attrs["twm.sample_count"], 34)
        self.assertEqual(attrs["twm.gate_status"], "pass")
        self.assertIn("twm.duration_ms", fake.span.attributes)


class TestGracefulDegradation(unittest.TestCase):
    def test_import_without_otel(self):
        """Module should import cleanly regardless of OTel availability."""
        import data_agent.otel_tracing as otel
        self.assertTrue(hasattr(otel, 'setup_otel_tracing'))
        self.assertTrue(hasattr(otel, 'trace_pipeline_run'))


if __name__ == "__main__":
    unittest.main()
