import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { fundsApi } from '../../api/funds';
import { getParsedApiError } from '../../api/error';
import { Badge, Button, Card, InlineAlert, Input } from '../common';
import type {
  FundHoldingImportItem,
  FundHoldingImportResponse,
  FundHoldingReviewResponse,
  FundSavedHoldingItem,
} from '../../types/funds';

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
  const [savedHoldings, setSavedHoldings] = useState<FundSavedHoldingItem[]>([]);
  const [saveMessage, setSaveMessage] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saveLoading, setSaveLoading] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [review, setReview] = useState<FundHoldingReviewResponse | null>(null);
  const [reviewError, setReviewError] = useState('');
  const [reviewLoading, setReviewLoading] = useState(false);
  const [aiReviewLoading, setAiReviewLoading] = useState(false);
  const [savedDrafts, setSavedDrafts] = useState<Record<number, Partial<FundHoldingImportItem>>>({});
  const [fieldSaveLoadingId, setFieldSaveLoadingId] = useState<number | null>(null);
  const holdingImageInputRef = useRef<HTMLInputElement | null>(null);

  const loadSavedHoldings = async () => {
    setListLoading(true);
    try {
      const data = await fundsApi.listHoldings();
      setSavedHoldings(data.items);
    } catch (err) {
      const parsed = getParsedApiError(err);
      setSaveError(parsed.message || '读取已保存基金持仓失败');
    } finally {
      setListLoading(false);
    }
  };

  useEffect(() => {
    void loadSavedHoldings();
  }, []);

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
    setSaveError('');
    setSaveMessage('');
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

  const normalizeFundCodeInput = (value: string) => value.replace(/\D/g, '').slice(0, 6);

  const updateImportedHolding = (
    index: number,
    patch: Partial<FundHoldingImportItem>,
  ) => {
    setHoldingImport((current) => {
      if (!current) return current;
      return {
        ...current,
        items: current.items.map((item, itemIndex) => (
          itemIndex === index ? { ...item, ...patch } : item
        )),
      };
    });
  };

  const saveRecognizedHoldings = async () => {
    if (!importedHoldings.length || saveLoading) return;

    setSaveError('');
    setSaveMessage('');
    setSaveLoading(true);
    try {
      const data = await fundsApi.saveHoldings(importedHoldings);
      setSaveMessage(`已保存 ${data.savedCount} 条基金持仓`);
      setReview(null);
      void loadSavedHoldings();
    } catch (err) {
      const parsed = getParsedApiError(err);
      setSaveError(parsed.message || '保存基金持仓失败');
    } finally {
      setSaveLoading(false);
    }
  };

  const getSavedDraftValue = (
    item: FundSavedHoldingItem,
    field: keyof FundHoldingImportItem,
  ): string => {
    const draft = savedDrafts[item.id]?.[field];
    const current = item[field];
    return String(draft ?? current ?? '');
  };

  const updateSavedDraft = (
    id: number,
    patch: Partial<FundHoldingImportItem>,
  ) => {
    setSavedDrafts((current) => ({
      ...current,
      [id]: {
        ...(current[id] || {}),
        ...patch,
      },
    }));
  };

  const saveSavedHoldingFields = async (item: FundSavedHoldingItem) => {
    if (fieldSaveLoadingId) return;
    const draft = savedDrafts[item.id] || {};
    const nextFundCode = normalizeFundCodeInput(String(draft.fundCode ?? item.fundCode ?? ''));
    if (nextFundCode && !/^\d{6}$/.test(nextFundCode)) {
      setSaveError('基金代码需要填写 6 位数字，例如 110020');
      return;
    }

    setSaveError('');
    setSaveMessage('');
    setFieldSaveLoadingId(item.id);
    try {
      await fundsApi.saveHoldings([{
        ...item,
        ...draft,
        fundCode: nextFundCode || null,
      }]);
      setSaveMessage(`已更新 ${item.fundName || nextFundCode || '持仓'} 的字段`);
      setReview(null);
      setSavedDrafts((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      await loadSavedHoldings();
    } catch (err) {
      const parsed = getParsedApiError(err);
      setSaveError(parsed.message || '更新基金持仓字段失败');
    } finally {
      setFieldSaveLoadingId(null);
    }
  };

  const loadReview = async (useAi = false) => {
    if (useAi) {
      setAiReviewLoading(true);
    } else {
      setReviewLoading(true);
    }
    setReviewError('');
    try {
      const data = await fundsApi.reviewHoldings(useAi);
      setReview(data);
    } catch (err) {
      const parsed = getParsedApiError(err);
      setReviewError(parsed.message || '基金持仓净值对齐失败');
    } finally {
      if (useAi) {
        setAiReviewLoading(false);
      } else {
        setReviewLoading(false);
      }
    }
  };

  const importedHoldings = holdingImport?.items || [];
  const importWarnings = holdingImport?.warnings || [];

  return (
    <div className="space-y-4">
      <Card title="我的基金持仓" subtitle="My position">
        <input
          ref={holdingImageInputRef}
          type="file"
          accept={HOLDING_IMAGE_EXT.join(',')}
          className="hidden"
          onChange={onHoldingImageSelected}
        />
        <p className="text-sm leading-6 text-secondary-text">
          支持上传支付宝、天天基金、养基宝等场外基金持仓截图。识别后先人工核对，基金代码可手动补齐，再保存到本地持仓库。
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
              setSaveError('');
              setSaveMessage('');
            }}
          >
            清空结果
          </Button>
        </div>

        <InlineAlert
          className="mt-3"
          variant="warning"
          title="先核对再保存"
          message="OCR 可能误读金额、份额或收益率。保存后的字段仍只作为持仓记录展示，暂不参与收益计算。"
        />

        {holdingImportError ? (
          <InlineAlert className="mt-3" variant="danger" title="导入失败" message={holdingImportError} />
        ) : null}
        {saveError ? (
          <InlineAlert className="mt-3" variant="danger" title="保存失败" message={saveError} />
        ) : null}
        {saveMessage ? (
          <InlineAlert className="mt-3" variant="success" title="保存成功" message={saveMessage} />
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
                    <Input
                      label="基金代码"
                      inputMode="numeric"
                      placeholder="6 位代码，如 110020"
                      value={item.fundCode || ''}
                      maxLength={6}
                      onChange={(event) => updateImportedHolding(index, {
                        fundCode: normalizeFundCodeInput(event.target.value),
                      })}
                      hint="识别不到代码时可以在这里补齐"
                    />
                    <Input
                      label="基金名称"
                      value={item.fundName || ''}
                      onChange={(event) => updateImportedHolding(index, {
                        fundName: event.target.value,
                      })}
                      hint="名称不准也可以一并修正"
                    />
                    <Input
                      label="持有金额"
                      placeholder="如 1234.56"
                      value={item.holdingAmount || ''}
                      onChange={(event) => updateImportedHolding(index, {
                        holdingAmount: event.target.value,
                      })}
                      hint="没有份额时可用金额反推份额"
                    />
                    <Input
                      label="持有份额"
                      placeholder="可选"
                      value={item.holdingShare || ''}
                      onChange={(event) => updateImportedHolding(index, {
                        holdingShare: event.target.value,
                      })}
                    />
                    <Input
                      label="持仓成本"
                      placeholder="可选"
                      value={item.costAmount || ''}
                      onChange={(event) => updateImportedHolding(index, {
                        costAmount: event.target.value,
                      })}
                      hint="没有成本时会尽量用收益反推"
                    />
                    <Input
                      label="截图净值"
                      placeholder="可选"
                      value={item.latestNav || ''}
                      onChange={(event) => updateImportedHolding(index, {
                        latestNav: event.target.value,
                      })}
                      hint="有截图净值时，份额反推更准确"
                    />
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
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="w-full"
              isLoading={saveLoading}
              loadingText="保存中..."
              onClick={() => void saveRecognizedHoldings()}
            >
              保存持仓
            </Button>
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

      <Card title="已保存持仓" subtitle={listLoading ? 'Loading' : `${savedHoldings.length} items`}>
        {savedHoldings.length ? (
          <div className="space-y-3">
            {savedHoldings.map((item, index) => {
              const confidence = confidenceMeta(item.confidence);
              return (
                <div
                  key={item.id || holdingImportKey(item, index)}
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
                    <CompactRow left="持有收益" right={holdingValue(item.holdingGain)} meta={holdingValue(item.holdingGainPct)} />
                  </div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <Input
                      label="基金代码"
                      inputMode="numeric"
                      placeholder="6 位代码"
                      value={getSavedDraftValue(item, 'fundCode')}
                      maxLength={6}
                      onChange={(event) => updateSavedDraft(item.id, {
                        fundCode: normalizeFundCodeInput(event.target.value),
                      })}
                      hint={item.fundCode ? '可修改已保存代码' : '自动匹配失败时在这里补齐'}
                    />
                    <Input
                      label="持有金额"
                      placeholder="如 1234.56"
                      value={getSavedDraftValue(item, 'holdingAmount')}
                      onChange={(event) => updateSavedDraft(item.id, {
                        holdingAmount: event.target.value,
                      })}
                      hint="可用来自动反推份额"
                    />
                    <Input
                      label="持有份额"
                      placeholder="可选"
                      value={getSavedDraftValue(item, 'holdingShare')}
                      onChange={(event) => updateSavedDraft(item.id, {
                        holdingShare: event.target.value,
                      })}
                    />
                    <Input
                      label="持仓成本"
                      placeholder="可选"
                      value={getSavedDraftValue(item, 'costAmount')}
                      onChange={(event) => updateSavedDraft(item.id, {
                        costAmount: event.target.value,
                      })}
                      hint="有收益字段时也会尝试反推"
                    />
                    <Input
                      label="截图净值"
                      placeholder="可选"
                      value={getSavedDraftValue(item, 'latestNav')}
                      onChange={(event) => updateSavedDraft(item.id, {
                        latestNav: event.target.value,
                      })}
                      hint="用于按截图金额反推真实份额"
                    />
                  </div>
                  <div className="mt-3 flex justify-end">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      isLoading={fieldSaveLoadingId === item.id}
                      loadingText="保存中..."
                      onClick={() => void saveSavedHoldingFields(item)}
                    >
                      保存字段
                    </Button>
                  </div>
                  <div className="mt-2 text-xs text-muted-text">
                    更新时间：{item.updatedAt || '--'}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm leading-6 text-muted-text">
            {listLoading ? '正在读取已保存持仓...' : '还没有保存持仓。识别并核对后点击“保存持仓”。'}
          </p>
        )}
      </Card>

      <Card title="净值对齐与建议" subtitle={review ? 'Latest NAV' : 'Review'}>
        <p className="text-sm leading-6 text-secondary-text">
          用最新公开净值对齐你已保存的基金份额，估算当前市值、相对截图变化和持仓建议。场外基金不是股票实时价，盘中估值只作为参考。
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={!savedHoldings.length || reviewLoading || aiReviewLoading}
            isLoading={reviewLoading}
            loadingText="刷新中..."
            onClick={() => void loadReview(false)}
          >
            刷新净值对齐
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!savedHoldings.length || reviewLoading || aiReviewLoading}
            isLoading={aiReviewLoading}
            loadingText="生成中..."
            onClick={() => void loadReview(true)}
          >
            AI增强建议
          </Button>
        </div>

        {reviewError ? (
          <InlineAlert className="mt-3" variant="danger" title="复盘失败" message={reviewError} />
        ) : null}

        {review ? (
          <div className="mt-3 space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <CompactRow left="可估值持仓" right={`${review.summary.pricedCount}/${review.summary.itemCount}`} />
              <CompactRow left="估算总市值" right={holdingValue(review.summary.totalEstimatedMarketValue)} />
              <CompactRow left="相对截图变化" right={holdingValue(review.summary.totalValueChangeFromSaved)} />
              <CompactRow left="估算总盈亏" right={holdingValue(review.summary.totalEstimatedGain)} />
            </div>

            {review.summary.aiSummary ? (
              <div className="rounded-2xl border border-cyan/20 bg-cyan/10 p-3 text-sm leading-6 text-foreground whitespace-pre-line">
                {review.summary.aiSummary}
              </div>
            ) : review.summary.aiError ? (
              <InlineAlert
                variant="info"
                title="AI增强未启用"
                message={review.summary.aiError}
              />
            ) : null}

            {review.items.map((item, index) => (
              <div
                key={`review-${item.id || index}`}
                className="rounded-2xl border border-subtle bg-surface/60 p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-foreground">
                      {item.fundName || item.fundCode || '未命名基金'}
                    </div>
                    <div className="mt-1 text-xs text-muted-text">
                      {item.fundCode || '代码待核对'} · {item.analysisLabel} · {item.riskLevel}
                    </div>
                  </div>
                  <Badge variant={item.analysisLabel === '回避' ? 'warning' : 'default'}>
                    {item.dataStatus === 'priced' ? '已对齐' : '待补全'}
                  </Badge>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <CompactRow
                    left="最新公开净值"
                    right={holdingValue(item.latestPublicNav)}
                    meta={item.latestNavDate || undefined}
                  />
                  <CompactRow left="最新日涨跌" right={holdingValue(item.latestDailyReturnPct)} />
                  <CompactRow
                    left="用于估算份额"
                    right={holdingValue(item.inferredHoldingShare || item.holdingShare)}
                    meta={item.inferredHoldingShare ? '自动反推' : undefined}
                  />
                  <CompactRow
                    left="用于估算成本"
                    right={holdingValue(item.inferredCostAmount || item.costAmount)}
                    meta={item.inferredCostAmount ? '自动反推' : undefined}
                  />
                  <CompactRow left="估算市值" right={holdingValue(item.estimatedMarketValue)} />
                  <CompactRow left="相对截图变化" right={holdingValue(item.valueChangeFromSaved)} />
                  <CompactRow left="估算盈亏" right={holdingValue(item.estimatedGain)} meta={holdingValue(item.estimatedGainPct)} />
                </div>
                <div className="mt-3 rounded-xl border border-subtle bg-card/40 px-3 py-2 text-sm leading-6 text-secondary-text">
                  {item.advice}
                </div>
                {item.reasons.length ? (
                  <div className="mt-2 space-y-1 text-xs leading-5 text-muted-text">
                    {item.reasons.slice(0, 3).map((reason) => (
                      <div key={reason}>依据：{reason}</div>
                    ))}
                  </div>
                ) : null}
                {item.valuationBasis?.length ? (
                  <div className="mt-2 space-y-1 text-xs leading-5 text-cyan">
                    {item.valuationBasis.slice(0, 3).map((basis) => (
                      <div key={basis}>估算：{basis}</div>
                    ))}
                  </div>
                ) : null}
                {item.evidenceGaps.length ? (
                  <div className="mt-2 space-y-1 text-xs leading-5 text-warning">
                    {item.evidenceGaps.slice(0, 3).map((gap) => (
                      <div key={gap}>缺口：{gap}</div>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}

            {review.summary.sourceNotes.length ? (
              <div className="space-y-1 text-xs leading-5 text-muted-text">
                {review.summary.sourceNotes.map((note) => (
                  <div key={note}>{note}</div>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <p className="mt-3 text-sm leading-6 text-muted-text">
            {savedHoldings.length ? '点击“刷新净值对齐”后查看估算浮动和持仓建议。' : '先导入并保存基金持仓，再做净值对齐。'}
          </p>
        )}
      </Card>
    </div>
  );
};
