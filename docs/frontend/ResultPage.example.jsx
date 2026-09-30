import { useLocation, useNavigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import axios from 'axios';
import { supabase } from './supabaseClient';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const LEVEL_CONFIG = {
  SAFE:    { bg: '#E8F5E9', border: '#4A7C59', color: '#2E6B43', icon: '✅', label: '섭취 가능' },
  CAUTION: { bg: '#FFF8E1', border: '#E8A838', color: '#7a5a00', icon: '⚠️', label: '확인 필요' },
  WARNING: { bg: '#FFEBEE', border: '#B94A2C', color: '#7a1a1a', icon: '🚫', label: '섭취 불가' },
};

// 로그인 토큰을 헤더에 실어 보낸다 (없으면 비로그인 분석)
async function authHeader() {
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {};
}

// 직원에게 들려줄 한국어 질문 (브라우저 내장 TTS — 별도 API 불필요)
function speakKo(text) {
  if (!('speechSynthesis' in window)) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ko-KR';
  u.rate = 0.9;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}

/* ── 위험 사유 한 줄 ── */
function ReasonLine({ r, color }) {
  const kindLabel = { allergy: '알레르기', religious: '종교 식단', religious_verify: '인증 확인 필요', diet: '채식' }[r.kind] || '';
  return (
    <div style={{ fontSize: 12, color, padding: '2px 0' }}>
      • {r.ingredient} — {r.label}
      {r.severity ? ` (${r.severity})` : ''} {kindLabel && `· ${kindLabel}`}
    </div>
  );
}

/* ── 직원 확인 질문 카드 ── */
function StaffQuestion({ item, question, onUpdated }) {
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState('');

  const answer = async (value) => {
    setSending(true);
    try {
      const res = await axios.post(
        `${API_URL}/qna/confirm`,
        {
          menu_result: item,
          question: {
            kind: question.kind,
            ingredient: question.ingredient,
            tag: question.tag,
            options: question.options || [],
          },
          staff_answer: value,
          input_type: 'text',
        },
        { headers: { ...(await authHeader()) }, timeout: 60000 }
      );
      setDone(res.data.result?.risk?.level || '');
      onUpdated(res.data.result); // 갱신된 결과로 카드 교체
    } catch (e) {
      alert('답변 반영에 실패했어요: ' + e.message);
    } finally {
      setSending(false);
    }
  };

  const isVariant = question.kind === 'variant';

  return (
    <div style={qBox}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>직원에게 보여주세요</div>
      <div style={{ fontSize: 17, fontWeight: 800, color: '#1A1A1A', lineHeight: 1.4 }}>{question.ko}</div>
      <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>{question.translated}</div>

      <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
        <button onClick={() => speakKo(question.ko)} style={ttsBtn}>🔊 한국어로 읽어주기</button>
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
        {isVariant
          ? (question.options || []).map((opt) => (
              <button key={opt} disabled={sending} onClick={() => answer(opt)} style={ansBtn('#1F6FB2')}>
                {opt}
              </button>
            ))
          : (
            <>
              <button disabled={sending} onClick={() => answer('예')} style={ansBtn('#B94A2C')}>예</button>
              <button disabled={sending} onClick={() => answer('아니요')} style={ansBtn('#4A7C59')}>아니요</button>
            </>
          )}
      </div>
      {done && <div style={{ marginTop: 8, fontSize: 12, fontWeight: 700 }}>→ 판정이 {done}(으)로 갱신됐어요</div>}
    </div>
  );
}

/* ── 메뉴 카드 ── */
function ResultCard({ item, onUpdated }) {
  const [open, setOpen] = useState(false);
  const cfg = LEVEL_CONFIG[item.risk.level] || LEVEL_CONFIG.CAUTION;

  const confirmed = item.risk.confirmed_reasons || [];
  const possible  = item.risk.possible_reasons  || [];
  const questions = item.risk.staff_questions   || [];
  const ingredients = item.ingredients || [];
  // 비율이 있는 재료만 그래프로, 없으면 이름만
  const withRatio = ingredients.filter((i) => typeof i.ratio_percent === 'number');
  const isRealRatio = ingredients.some((i) => i.ratio_source === 'menuzen');

  return (
    <div style={{ ...cardBase, borderColor: cfg.border, background: cfg.bg }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
        <span style={{ fontSize: 28 }}>{cfg.icon}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 900, fontSize: 17, color: '#1A1A1A' }}>{item.menu}</div>
          <div style={{ fontSize: 12, color: '#555' }}>{item.menu_translated}</div>
          <div style={{ fontSize: 12, fontWeight: 700, color: cfg.color, letterSpacing: 1 }}>
            {item.risk.level} — {cfg.label}
          </div>
        </div>
        <button onClick={() => setOpen((v) => !v)} style={toggleBtn}>{open ? '접기' : '상세'}</button>
      </div>

      {item.description_translated && (
        <div style={{ fontSize: 12, color: '#555', marginBottom: 8 }}>{item.description_translated}</div>
      )}

      {/* 확정 사유 */}
      {confirmed.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          {confirmed.map((r, i) => <ReasonLine key={i} r={r} color={cfg.color} />)}
        </div>
      )}

      {/* 가능성 사유 */}
      {possible.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ fontSize: 11, color: '#888' }}>가게에 따라 다를 수 있음</div>
          {possible.map((r, i) => <ReasonLine key={i} r={r} color="#7a5a00" />)}
        </div>
      )}

      {/* 직원 확인 질문 */}
      {questions.map((q, i) => (
        <StaffQuestion key={i} item={item} question={q} onUpdated={onUpdated} />
      ))}

      {/* 상세 */}
      {open && (
        <div style={{ borderTop: `1px solid ${cfg.border}`, marginTop: 8, paddingTop: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 800, marginBottom: 6 }}>
            성분 구성 {isRealRatio ? '(공공데이터 실제 중량 기준)' : '(AI 추정치)'}
          </div>
          {withRatio.map((ing, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 12, width: 140, color: ing.tags?.length ? '#1A1A1A' : '#666', fontWeight: ing.tags?.length ? 700 : 400 }}>
                {ing.name}
              </span>
              <div style={{ flex: 1, height: 8, background: '#00000014', borderRadius: 4 }}>
                <div style={{ width: `${Math.min(ing.ratio_percent, 100)}%`, height: '100%', background: cfg.border, borderRadius: 4 }} />
              </div>
              <span style={{ fontSize: 11, width: 42, textAlign: 'right' }}>{ing.ratio_percent}%</span>
            </div>
          ))}

          {/* 비율 정보가 없는 재료 */}
          <div style={{ fontSize: 12, color: '#555', marginTop: 8 }}>
            {ingredients
              .filter((i) => typeof i.ratio_percent !== 'number')
              .map((i) => i.name + (i.certainty === 'possible' ? '(가능)' : ''))
              .join(', ')}
          </div>

          {item.data_source && (
            <div style={{ fontSize: 11, color: '#888', marginTop: 10 }}>
              판정 근거: {{ menuzen: '공공데이터(메뉴젠)', menu_base: '자체 메뉴 DB', menu_board: '메뉴판 표기', ai: 'AI 추론' }[item.data_source]}
              {item.family?.length > 1 && ` · 유사 레시피 ${item.family.length}종 비교`}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ResultPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [disclaimer, setDisclaimer] = useState('');

  // ScanPage에서 넘어온 값
  const menus = location.state?.menus;      // [{name, price}] — 이쪽이 더 정확
  const ocrText = location.state?.ocrText;  // 예비

  useEffect(() => {
    if (menus?.length || ocrText) fetchAnalysis();
  }, []);

  const fetchAnalysis = async () => {
    setLoading(true);
    setError('');
    try {
      const body = menus?.length ? { menus } : { ocr_text: ocrText };
      const res = await axios.post(`${API_URL}/analyze`, body, {
        headers: { ...(await authHeader()) },
        timeout: 180000, // 메뉴가 많으면 오래 걸림 (무료 등급 호출 제한)
      });
      setResults(res.data.results || []);
      setDisclaimer(res.data.disclaimer || '');
      if (!res.data.profile_applied) {
        setError('프로필이 적용되지 않았어요. 로그인 후 프로필을 설정하면 개인 맞춤으로 판정됩니다.');
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (err.message?.includes('Network Error')) setError('백엔드 서버에 연결할 수 없어요. 서버가 실행 중인지 확인해주세요.');
      else if (err.code === 'ECONNABORTED') setError('분석이 오래 걸리고 있어요. 메뉴 수를 줄여 다시 시도해주세요.');
      else if (err.response?.status === 401) setError('로그인이 만료됐어요. 다시 로그인해주세요.');
      else setError(`오류가 발생했어요: ${detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 직원 답변 후 갱신된 결과로 교체
  // 메뉴판에 같은 이름의 메뉴가 두 번 나올 수 있으므로(예: 해물탕 소/대)
  // 이름이 아니라 카드 순번으로 교체한다.
  const handleUpdated = (index, updated) => {
    setResults((prev) => prev.map((r, i) => (i === index ? updated : r)));
  };

  const summary = {
    WARNING: results.filter((r) => r.risk?.level === 'WARNING').length,
    CAUTION: results.filter((r) => r.risk?.level === 'CAUTION').length,
    SAFE: results.filter((r) => r.risk?.level === 'SAFE').length,
  };

  return (
    <div style={pageStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <button onClick={() => navigate('/scan')} style={backBtn}>← 다시 스캔</button>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 900 }}>📊 분석 결과</h2>
      </div>

      {results.length > 0 && (
        <div style={summaryRow}>
          {Object.entries(summary).map(([level, count]) => {
            const cfg = LEVEL_CONFIG[level];
            return (
              <div key={level} style={{ ...summaryBadge, background: cfg.bg, borderColor: cfg.border, color: cfg.color }}>
                {cfg.icon} {level} {count}개
              </div>
            );
          })}
        </div>
      )}

      {loading && <div style={loadingBox}>🧠 AI가 성분을 분석 중이에요...</div>}
      {error && <div style={errorBox}>⚠️ {error}</div>}

      {results.map((item, i) => (
        <ResultCard key={`${item.menu}-${i}`} item={item} onUpdated={(updated) => handleUpdated(i, updated)} />
      ))}

      {disclaimer && <div style={{ fontSize: 11, color: '#888', marginTop: 16 }}>※ {disclaimer}</div>}
    </div>
  );
}

/* ── styles ── */
const pageStyle = { maxWidth: 560, margin: '0 auto', padding: 20 };
const cardBase = { border: '2px solid', borderRadius: 14, padding: 16, marginBottom: 14 };
const toggleBtn = { border: '1px solid #ccc', background: '#fff', borderRadius: 8, padding: '4px 10px', fontSize: 12, cursor: 'pointer' };
const backBtn = { border: '1px solid #ddd', background: '#fff', borderRadius: 8, padding: '6px 12px', fontSize: 13, cursor: 'pointer' };
const summaryRow = { display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' };
const summaryBadge = { border: '1px solid', borderRadius: 999, padding: '4px 12px', fontSize: 12, fontWeight: 700 };
const loadingBox = { padding: 20, textAlign: 'center', color: '#555' };
const errorBox = { padding: 12, background: '#FFF4F4', border: '1px solid #E8C0C0', borderRadius: 10, fontSize: 13, marginBottom: 12 };
const qBox = { background: '#fff', border: '1px dashed #E8A838', borderRadius: 10, padding: 12, marginTop: 8 };
const ttsBtn = { border: '1px solid #1F6FB2', color: '#1F6FB2', background: '#fff', borderRadius: 8, padding: '5px 12px', fontSize: 12, cursor: 'pointer' };
const ansBtn = (c) => ({ border: 'none', background: c, color: '#fff', borderRadius: 8, padding: '8px 18px', fontSize: 13, fontWeight: 700, cursor: 'pointer' });
