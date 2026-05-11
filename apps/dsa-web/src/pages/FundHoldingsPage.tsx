import type React from 'react';
import { useEffect } from 'react';
import { FundHoldingImportPanel } from '../components/funds/FundHoldingImportPanel';
import { Card } from '../components/common';

const FundHoldingsPage: React.FC = () => {
  useEffect(() => {
    document.title = '基金持仓 - DSA';
  }, []);

  return (
    <div className="flex min-h-full flex-col gap-4 p-3 md:p-5">
      <header className="rounded-[1.5rem] border border-subtle bg-card/70 p-4 shadow-soft-card">
        <span className="label-uppercase">场外基金账户</span>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">基金持仓</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-secondary-text">
          这里放你的个人基金账户数据，和“基金分析”里的单只基金公开资料分开。当前支持截图识别、人工核对和保存入库；组合收益与成本分析后续接入。
        </p>
      </header>

      <main className="grid items-start gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <section className="space-y-4">
          <FundHoldingImportPanel />
        </section>

        <aside className="space-y-4">
          <Card title="为什么独立成菜单" subtitle="Account scope">
            <div className="space-y-3 text-sm leading-6 text-secondary-text">
              <p>基金分析页关注单只基金的净值、估值、重仓和费用。</p>
              <p>基金持仓页关注你自己的账户金额、份额、成本和收益，后续会演进为组合维度。</p>
            </div>
          </Card>

          <Card title="当前状态" subtitle="MVP">
            <div className="space-y-2">
              <div className="rounded-xl border border-subtle bg-surface/50 px-3 py-2 text-sm">
                <div className="text-secondary-text">识别结果</div>
                <div className="mt-1 font-mono text-foreground">预览核对</div>
              </div>
              <div className="rounded-xl border border-subtle bg-surface/50 px-3 py-2 text-sm">
                <div className="text-secondary-text">保存入库</div>
                <div className="mt-1 font-mono text-foreground">可用</div>
              </div>
              <div className="rounded-xl border border-subtle bg-surface/50 px-3 py-2 text-sm">
                <div className="text-secondary-text">收益计算</div>
                <div className="mt-1 font-mono text-muted-text">暂不参与</div>
              </div>
            </div>
          </Card>
        </aside>
      </main>
    </div>
  );
};

export default FundHoldingsPage;
