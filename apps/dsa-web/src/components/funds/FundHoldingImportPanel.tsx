import type React from 'react';
import { useRef, useState } from 'react';
import { fundsApi } from '../../api/funds';
import { getParsedApiError } from '../../api/error';
import { Badge, Button, Card, InlineAlert } from '../common';
import type { FundHoldingImportItem, FundHoldingImportResponse } from '../../types/funds';

const HOLDING_IMAGE_EXT = ['.jpg', '.jpeg', '.png', '.webp', '.gif'];
const HOLDING_IMAGE_MAX = 5 * 1024 * 1024;

function confidenceMeta(confidence?: string | null): { label: string; variant: 'success' | 'warning' | 'default' } {
  if (confidence === 'high') return { label: '高置信', variant: 'success' };
  if (confidence === 'low') return { label: '低置信', variant: 'warning' };
  return { label: '中置信', variant: 'default' };
}

function holdingValue(value?: string | null): string {
  return value?.trim() || '--';
}

function holdingImportKey(item: FundHoldingImportItem, index: number): string {
  return `${item.fundCode || item.fundName || 'fund'}-${item.platform || 'platform'}-${index}`;
}

const CompactRow: React.FC<{ left: string; right: string; meta?: string; tone?: string }> = ({
  left,
  right,
  meta,
  tone,
}) => (
  <div className="flex items-center justify-between gap-3 rounded-xl border border-subtle bg-surface/50 px-3 py-2 text-sm">
    <div className="min-w-0">
      <div className="truncate text-secondary-text">{left}</div>
      {meta ? <div className="mt-0.5 truncate text-xs text-muted-text">{meta}</div> : null}
    </div>
    <div className={`shrink-0 font-mono ${tone || 'text-foreground'}`}>{right}</div>
  </div>
);

export const FundHoldingImportPanel: React.FC = () => {
  const [holdingImport, setHoldingImport] = useState<FundHoldingImportResponse | null>(null);
  const [holdingImportError, setHoldingImportError] = useState('');
  const [holdingImportLoading, setHoldingImportLoading] = useState(false);
  const holdingImageInputRef = useRef<HTMLInputElement | null>(null);

  const importHoldingImage = async (file: File) => {
    const ext = `.${(file.name.split('.').pop() || '').toLowerCase()}`;
    if (!HOLDING_IMAGE_EXT.includes(ext)) {
      setHoldingImportError('图片仅支持 JPG、PNG、WebP、GIF');
      return;
    }
    if (file.size > HOLDING_IMAGE_MAX) {
      setHoldingImportError('图片不超过 5MB');
      return;
    }

    setHoldingImportError('');
    setHoldingImportLoading(true);
    try {
      const data = await fundsApi.importHoldingsImage(file);
      setHoldingImport(data);
    } catch (err) {
      const parsed = getParsedApiError(err);
      const axiosLike = err && typeof err === 'object'
        ? (err as { response?: { status?: number }; code?: string })
        : null;
      if (axiosLike?.response?.status === 429) {
        setHoldingImportError('请求过于频繁，请稍后再试');
      } else if (axiosLike?.code === 'ECONNABORTED') {
        setHoldingImportError('识别超时，请检查网络或换一张更清晰的截图');
      } else {
        setHoldingImportError(parsed.message || '基金持仓截图识别失败');
      }
    } finally {
      setHoldingImportLoading(false);
    }
  };

  const onHoldingImageSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) void importHoldingImage(file);
    event.target.value = '';
  };

  const openHoldingImagePicker = () => {
    if (!holdingImportLoading) holdingImageInputRef.current?.click();
  };

  const importedHoldings = holdingImport?.items || [];
  const importWarnings = holdingImport?.warnings || [];

  return (
    <Card title="我的基金持仓" subtitle="My position">
      <input
        ref={holdingImageInputRef}
        type="file"
        accept={HOLDING_IMAGE_EXT.join(',')}
        className="hidden"
        onChange={onHoldingImageSelected}
      />
      <p className="text-sm leading-6 text-secondary-text">
        支持上传支付宝、天天基金、养基宝等场外基金持仓截图。当前版本只做识别预览和人工核对，不会自动写入真实持仓库。
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          isLoading={holdingImportLoading}
          loadingText="识别中..."
          onClick={openHoldingImagePicker}
        >
          导入持仓截图
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={!holdingImport || holdingImportLoading}
          onClick={() => {
            setHoldingImport(null);
            setHoldingImportError('');
          }}
        >
          清空结果
        </Button>
      </div>

      <InlineAlert
        className="mt-3"
        variant="warning"
        title="先核对再使用"
        message="OCR 可能误读金额、份额或收益率，识别结果暂不参与收益计算，也不会影响现有股票分析。"
      />

      {holdingImportError ? (
        <InlineAlert className="mt-3" variant="danger" title="导入失败" message={holdingImportError} />
      ) : null}

      {importWarnings.length ? (
        <div className="mt-3 rounded-2xl border border-warning/20 bg-warning/10 p-3 text-xs leading-5 text-warning">
          {importWarnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}

      {importedHoldings.length ? (
        <div className="mt-3 space-y-3">
          {importedHoldings.map((item, index) => {
            const confidence = confidenceMeta(item.confidence);
            return (
              <div
                key={holdingImportKey(item, index)}
                className="rounded-2xl border border-subtle bg-surface/60 p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-foreground">
                      {item.fundName || item.fundCode || '未命名基金'}
                    </div>
                    <div className="mt-1 text-xs text-muted-text">
                      {item.fundCode || '代码待核对'} · {item.platform || '平台未知'}
                    </div>
                  </div>
                  <Badge variant={confidence.variant}>{confidence.label}</Badge>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <CompactRow left="持有金额" right={holdingValue(item.holdingAmount)} />
                  <CompactRow left="持有份额" right={holdingValue(item.holdingShare)} />
                  <CompactRow left="持仓成本" right={holdingValue(item.costAmount)} />
                  <CompactRow left="成本净值" right={holdingValue(item.costNav)} />
                  <CompactRow left="最新净值" right={holdingValue(item.latestNav)} />
                  <CompactRow
                    left="持有收益"
                    right={holdingValue(item.holdingGain)}
                    meta={holdingValue(item.holdingGainPct)}
                  />
                  <CompactRow left="昨日收益" right={holdingValue(item.yesterdayGain)} />
                  <CompactRow left="币种" right={item.currency || 'CNY'} />
                </div>
                {item.warnings?.length ? (
                  <div className="mt-3 space-y-1 text-xs text-warning">
                    {item.warnings.map((warning) => (
                      <div key={warning}>{warning}</div>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
          <Button type="button" size="sm" variant="outline" disabled className="w-full">
            保存持仓（下一步）
          </Button>
          <p className="text-xs leading-5 text-muted-text">
            下一步再接保存、组合收益和真实成本分析；现在先把截图识别入口打通。
          </p>
        </div>
      ) : holdingImport ? (
        <InlineAlert
          className="mt-3"
          variant="info"
          title="未识别到基金持仓"
          message="可以换一张包含基金名称、金额或份额的持仓明细截图重试。"
        />
      ) : (
        <div className="mt-3 space-y-2">
          <CompactRow left="导入方式" right="可导入" meta="截图识别" />
          <CompactRow left="核心字段" right="预览核对" meta="金额 / 份额 / 成本" />
        </div>
      )}
    </Card>
  );
};
