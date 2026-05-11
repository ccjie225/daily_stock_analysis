import type React from 'react';
import { useEffect, useState } from 'react';
import { fundsApi } from '../api/funds';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { ApiErrorAlert, Badge, Card, EmptyState } from '../components/common';
import type { FundAnalysisResponse } from '../types/funds';

const FUND_CODE_RE = /^\d{6}$/;

function pct(value?: number | null): string {
  if (value == null) return '--';
  return `${value.toFixed(2)}%`;
}

function numberText(value?: number | null, digits = 4): string {
  if (value == null) return '--';
  return value.toFixed(digits);
}

function ratioText(value?: number | null): string {
  if (value == null) return '--';
  return value.toFixed(2);
}

function percentileTone(value?: number | null): string {
  if (value == null) return 'text-foreground';
  if (value >= 80) return 'text-danger';
  if (value <= 25) return 'text-success';
  return 'text-warning';
}

function labelVariant(label: string): 'success' | 'warning' | 'danger' | 'info' {
  if (label === '候选') return 'success';
  if (label === '回避') return 'danger';
  if (label === '信息不足') return 'info';
  return 'warning';
}

function riskLabel(level: string): string {
  switch (level) {
    case 'low':
      return '低风险';
    case 'medium':
      return '中风险';
    case 'high':
      return '高风险';
    default:
      return '待确认';
  }
}

function riskVariant(level: string): 'success' | 'warning' | 'danger' | 'default' {
  switch (level) {
    case 'low':
      return 'success';
    case 'medium':
      return 'warning';
    case 'high':
      return 'danger';
    default:
      return 'default';
  }
}

const Metric: React.FC<{ label: string; value: string; tone?: string }> = ({ label, value, tone }) => (
  <div className="rounded-2xl border border-subtle bg-surface/60 p-4">
    <div className="text-xs text-muted-text">{label}</div>
    <div className={`mt-2 text-lg font-semibold ${tone || 'text-foreground'}`}>{value}</div>
  </div>
);

const CompactRow: React.FC<{ left: string; right: string; meta?: string; tone?: string }> = ({ left, right, meta, tone }) => (
  <div className="flex items-center justify-between gap-3 rounded-xl border border-subtle bg-surface/50 px-3 py-2 text-sm">
    <div className="min-w-0">
      <div className="truncate text-secondary-text">{left}</div>
      {meta ? <div className="mt-0.5 truncate text-xs text-muted-text">{meta}</div> : null}
    </div>
    <div className={`shrink-0 font-mono ${tone || 'text-foreground'}`}>{right}</div>
  </div>
);

const ListBlock: React.FC<{ title: string; items: string[]; empty: string }> = ({ title, items, empty }) => (
  <Card padding="md" className="h-full">
    <h3 className="text-sm font-semibold text-foreground">{title}</h3>
    {items.length > 0 ? (
      <ul className="mt-3 space-y-2 text-sm text-secondary-text">
        {items.map((item) => (
          <li key={item} className="rounded-xl border border-subtle bg-surface/50 px-3 py-2">
            {item}
          </li>
        ))}
      </ul>
    ) : (
      <p className="mt-3 text-sm text-muted-text">{empty}</p>
    )}
  </Card>
);

const FundsPage: React.FC = () => {
  const [fundCode, setFundCode] = useState('005918');
  const [days, setDays] = useState('365');
  const [result, setResult] = useState<FundAnalysisResponse | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [inputError, setInputError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    document.title = '基金分析 - DSA';
  }, []);

  const submit = async () => {
    const code = fundCode.trim();
    if (!FUND_CODE_RE.test(code)) {
      setInputError('请输入 6 位场外基金代码，例如 005918、110011、161725');
      return;
    }

    const parsedDays = Number.parseInt(days, 10);
    if (!Number.isFinite(parsedDays) || parsedDays < 30 || parsedDays > 1825) {
      setInputError('观察天数必须在 30 到 1825 之间');
      return;
    }

    setInputError('');
    setError(null);
    setLoading(true);
    try {
      const data = await fundsApi.analyze(code, parsedDays);
      setResult(data);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoading(false);
    }
  };

  const latest = result?.latestNav;
  const profile = result?.profile;
  const valuation = result?.referenceValuation;
  const peer = result?.peerAnalysis;
  const fees = result?.fees;
  const navTail = result?.nav.slice(-5).reverse() || [];
  const holdings = result?.holdings || [];
  const industries = result?.industryAllocation || [];

  return (
    <div className="flex min-h-full flex-col gap-4 p-3 md:p-5">
      <header className="rounded-[1.5rem] border border-subtle bg-card/70 p-4 shadow-soft-card">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <span className="label-uppercase">场外公募基金</span>
            <h1 className="mt-1 text-2xl font-semibold text-foreground">基金分析</h1>
            <p className="mt-2 max-w-2xl text-sm text-secondary-text">
              第一版只分析公开净值和基础资料，不登录支付宝/天天基金账户。后续可继续接入你的真实持仓成本和份额。
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              value={fundCode}
              onChange={(event) => setFundCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void submit();
              }}
              placeholder="基金代码，如 005918"
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-4 text-sm"
            />
            <input
              value={days}
              onChange={(event) => setDays(event.target.value.replace(/\D/g, '').slice(0, 4))}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void submit();
              }}
              placeholder="观察天数"
              className="input-surface input-focus-glow h-11 w-28 rounded-xl border bg-transparent px-4 text-sm"
            />
            <button
              type="button"
              className="btn-primary h-11 whitespace-nowrap"
              disabled={loading}
              onClick={() => void submit()}
            >
              {loading ? '分析中...' : '分析基金'}
            </button>
          </div>
        </div>
        {inputError ? <p className="mt-3 text-sm text-danger">{inputError}</p> : null}
      </header>

      {error ? <ApiErrorAlert error={error} /> : null}

      {!result && !loading ? (
        <EmptyState
          title="先输入一只场外基金"
          description="例如 005918、110011、161725。系统会拉取公开净值，计算收益、回撤和波动。"
          className="min-h-[18rem] border-dashed"
        />
      ) : null}

      {result ? (
        <main className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
          <section className="space-y-4">
            <Card variant="gradient" padding="lg">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-2xl font-semibold text-foreground">
                      {profile?.fundName || profile?.fundCode}
                    </h2>
                    <Badge variant={labelVariant(result.label)} glow>{result.label}</Badge>
                    <Badge variant={riskVariant(result.risk.riskLevel)}>{riskLabel(result.risk.riskLevel)}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-secondary-text">
                    {profile?.fundCode} · {profile?.fundType || '类型待确认'} · 数据源：{profile?.source}
                  </p>
                </div>
                <div className="text-right">
                  <div className="text-xs text-muted-text">最新单位净值</div>
                  <div className="mt-1 text-2xl font-semibold text-foreground">{numberText(latest?.unitNav)}</div>
                  <div className="mt-1 text-xs text-secondary-text">{latest?.date || '--'}</div>
                </div>
              </div>
              <p className="mt-5 rounded-2xl border border-subtle bg-surface/60 p-4 text-sm leading-6 text-secondary-text">
                {result.summary}
              </p>
            </Card>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Metric label="近 1 月" value={pct(result.returns.oneMonthPct)} tone={(result.returns.oneMonthPct || 0) >= 0 ? 'text-success' : 'text-danger'} />
              <Metric label="近 3 月" value={pct(result.returns.threeMonthPct)} tone={(result.returns.threeMonthPct || 0) >= 0 ? 'text-success' : 'text-danger'} />
              <Metric label="近 6 月" value={pct(result.returns.sixMonthPct)} tone={(result.returns.sixMonthPct || 0) >= 0 ? 'text-success' : 'text-danger'} />
              <Metric label="近 1 年" value={pct(result.returns.oneYearPct)} tone={(result.returns.oneYearPct || 0) >= 0 ? 'text-success' : 'text-danger'} />
              <Metric label="最大回撤" value={pct(result.risk.maxDrawdownPct)} tone="text-danger" />
              <Metric label="当前回撤" value={pct(result.risk.latestDrawdownPct)} />
              <Metric label="年化波动率" value={pct(result.risk.volatilityAnnualizedPct)} />
              <Metric label="累计净值" value={numberText(latest?.accumulatedNav)} />
            </div>

            <Card title="估值参考" subtitle={valuation?.referenceName || 'Valuation'}>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Metric label="参考 PE" value={ratioText(valuation?.peTtm)} />
                <Metric label="PE 历史分位" value={pct(valuation?.pePercentile)} tone={percentileTone(valuation?.pePercentile)} />
                <Metric label="参考 PB" value={ratioText(valuation?.pb)} />
                <Metric label="PB 历史分位" value={pct(valuation?.pbPercentile)} tone={percentileTone(valuation?.pbPercentile)} />
              </div>
              <div className="mt-3 rounded-2xl border border-subtle bg-surface/50 p-3 text-sm text-secondary-text">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={valuation?.referenceType === 'index' ? 'info' : 'default'}>
                    {valuation?.referenceType === 'index' ? '指数估值' : '估值待映射'}
                  </Badge>
                  <span>参考对象：{valuation?.referenceName || '待匹配'}</span>
                  {valuation?.asOfDate ? <span>日期：{valuation.asOfDate}</span> : null}
                </div>
                {valuation?.notes?.length ? (
                  <ul className="mt-2 space-y-1 text-xs text-muted-text">
                    {valuation.notes.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                ) : null}
              </div>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <ListBlock title="核心理由" items={result.reasons} empty="暂无正向理由，建议先观察数据完整性。" />
              <ListBlock title="主要风险" items={result.risks} empty="暂无显著风险，但仍需结合持仓和费用确认。" />
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <Card title="重仓持股" subtitle={holdings[0]?.reportPeriod || 'Top holdings'}>
                {holdings.length ? (
                  <div className="space-y-2">
                    {holdings.slice(0, 10).map((item) => (
                      <CompactRow
                        key={`${item.reportPeriod}-${item.stockCode}-${item.stockName}`}
                        left={item.stockName || item.stockCode}
                        meta={item.stockCode}
                        right={pct(item.weightPct)}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-text">暂无重仓股披露数据，无法判断持仓集中度。</p>
                )}
              </Card>

              <Card title="行业配置" subtitle={industries[0]?.reportDate || 'Industry'}>
                {industries.length ? (
                  <div className="space-y-2">
                    {industries.slice(0, 8).map((item) => (
                      <CompactRow
                        key={`${item.reportDate}-${item.industry}`}
                        left={item.industry}
                        right={pct(item.weightPct)}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-text">暂无行业配置披露数据，主题暴露需要继续补充。</p>
                )}
              </Card>
            </div>
          </section>

          <aside className="space-y-4">
            <Card title="基金画像" subtitle="Profile">
              <div className="space-y-3 text-sm">
                <div className="flex justify-between gap-3">
                  <span className="text-muted-text">基金经理</span>
                  <span className="text-right text-secondary-text">{profile?.manager || '待确认'}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-muted-text">基金规模</span>
                  <span className="text-right text-secondary-text">{profile?.assetSize || '待确认'}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-muted-text">成立日期</span>
                  <span className="text-right text-secondary-text">{profile?.inceptionDate || '待确认'}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-muted-text">托管人</span>
                  <span className="text-right text-secondary-text">{profile?.custodian || '待确认'}</span>
                </div>
              </div>
            </Card>

            <Card title="同类对比" subtitle={peer?.period || 'Peer'}>
              {peer ? (
                <div className="space-y-2">
                  <CompactRow left="风险收益评分" right={ratioText(peer.riskReturnScore)} />
                  <CompactRow left="抗风险波动评分" right={ratioText(peer.antiRiskScore)} />
                  <CompactRow left="夏普比率" right={ratioText(peer.sharpeRatio)} />
                  <CompactRow left="同类源最大回撤" right={pct(peer.maxDrawdownPct)} tone="text-danger" />
                </div>
              ) : (
                <p className="text-sm text-muted-text">暂无同类风险收益数据。</p>
              )}
            </Card>

            <Card title="费用规则" subtitle="Fees">
              <div className="space-y-2">
                <CompactRow left="管理费" right={pct(fees?.managementFeePct)} />
                <CompactRow left="托管费" right={pct(fees?.custodianFeePct)} />
                <CompactRow left="销售服务费" right={pct(fees?.salesServiceFeePct)} />
                <CompactRow left="短持有赎回费" right={pct(fees?.shortTermRedemptionFeePct)} tone={(fees?.shortTermRedemptionFeePct || 0) > 0 ? 'text-danger' : undefined} />
              </div>
              {fees?.items?.length ? (
                <div className="mt-3 space-y-2">
                  {fees.items.slice(0, 5).map((item) => (
                    <CompactRow
                      key={`${item.feeType}-${item.condition}-${item.feePct}`}
                      left={item.condition || item.feeType}
                      meta={item.feeType}
                      right={item.feeText || pct(item.feePct)}
                    />
                  ))}
                </div>
              ) : null}
            </Card>

            <Card title="最近净值" subtitle="NAV">
              <div className="space-y-2">
                {navTail.map((point) => (
                  <div key={point.date} className="flex items-center justify-between rounded-xl border border-subtle bg-surface/50 px-3 py-2 text-sm">
                    <span className="text-muted-text">{point.date}</span>
                    <span className="font-mono text-foreground">{numberText(point.unitNav)}</span>
                    <span className={(point.dailyReturnPct || 0) >= 0 ? 'text-success' : 'text-danger'}>
                      {pct(point.dailyReturnPct)}
                    </span>
                  </div>
                ))}
              </div>
            </Card>

            <ListBlock
              title="证据缺口"
              items={result.evidenceGaps}
              empty="基础净值数据已满足第一版分析。接入个人持仓后可继续补充成本和份额。"
            />
          </aside>
        </main>
      ) : null}
    </div>
  );
};

export default FundsPage;
