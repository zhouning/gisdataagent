import { useRef, useEffect } from 'react';
import ReactECharts from 'echarts-for-react';

interface ChartViewProps {
  option: any;
  chartId?: string;
  height?: string;
  compact?: boolean;
  onReady?: (instance: any) => void;
}

export default function ChartView({ option, chartId, height, compact, onReady }: ChartViewProps) {
  const chartRef = useRef<any>(null);

  useEffect(() => {
    if (chartRef.current && onReady) {
      onReady(chartRef.current.getEchartsInstance());
    }
  }, [onReady]);

  if (!option || typeof option !== 'object') {
    return <div className="chart-empty">无图表数据</div>;
  }

  const style = {
    height: height || (compact ? '200px' : '360px'),
    width: '100%',
  };

  return (
    <div className="chart-view-container" data-chart-id={chartId}>
      <ReactECharts
        ref={chartRef}
        option={option}
        style={style}
        opts={{ renderer: 'canvas' }}
        notMerge={true}
        lazyUpdate={true}
      />
    </div>
  );
}
