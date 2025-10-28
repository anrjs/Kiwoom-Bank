// App.tsx
import { useState, useEffect, useRef } from "react";
import { LoginPage } from "./components/LoginPage";
import { MainDashboard } from "./components/MainDashboard";
import { CompanyAnalysis } from "./components/CompanyAnalysis";
import { MyCompaniesList } from "./components/MyCompaniesList";
import { NotificationDetail } from "./components/NotificationDetail";
import { DeepAnalysisDashboard } from "./components/DeepAnalysisDashboard";
import { NotificationInbox } from "./components/NotificationInbox"; // ❗️ 'Notification' import는 이 파일에서 가져옵니다.
import type { Notification } from "./components/NotificationInbox"; // ❗️ Type만 따로 import
import { Toaster, toast } from "sonner"; // ❗️ sonner@2.0.3 제거
import axios from "axios"; // ❗️ 추가

type Screen =
  | "login"
  | "dashboard"
  | "company"
  | "mylist"
  | "notification"
  | "analysis"
  | "inbox";

export interface Company {
  name: string;
  rating: string;
  loanAmount: number;
  interestRate: number;
  delinquency: string;
  collateral: string;
  rm: string;
  ratingChange: string;
}

// ======== 🔧 추가: 실시간 모니터링 설정 ========
const API_BASE = import.meta?.env?.VITE_API_BASE_URL || "http://localhost:8000";
const WATCHLIST = ["삼성전자", "키움증권", "현대자동차"];
const POLL_MS = 3 * 60 * 1000; // 3분

// 등급 순위 비교 맵
const getRatingOrder = (r?: string | null) => {
  if (!r) return 999;
  const map: Record<string, number> = {
    AAA: 1, "AA+": 2, AA: 3, "AA-": 4,
    "A+": 5, A: 6, "A-": 7,
    "BBB+": 8, BBB: 9, "BBB-": 10,
    "BB+": 11, BB: 12, "BB-": 13,
    "B+": 14, B: 15, "B-": 16,
    "CCC+": 17, CCC: 18, "CCC-": 19,
    CC: 20, C: 21, D: 22,
  };
  return map[r] ?? 999;
};
// ==========================================

export default function App() {
  const [currentScreen, setCurrentScreen] = useState<Screen>("login");
  const [selectedCompany, setSelectedCompany] = useState<string>("");
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([{
    id: 9999, // 아무 숫자
    type: "down",
    companyName: "삼성전자", // 테스트할 회사 이름
    title: "테스트: 신용 등급 하향 조정 (개발용)",
    ratingChange: "AAA → AA",
    newsKeywords: "이것은 개발용 테스트 알림입니다.",
    timestamp: new Date().toLocaleString("ko-KR"),
    isRead: false,
  },]);
  const [selectedNotificationId, setSelectedNotificationId] = useState<number | null>(null);
  const [screenHistory, setScreenHistory] = useState<Screen[]>([]);
  const [myCompanies, setMyCompanies] = useState<Company[]>([
    // ... (기존 myCompanies 데이터와 동일) ...
    {
      name: "삼성전자",
      rating: "AAA",
      loanAmount: 5000,
      interestRate: 3.2,
      delinquency: "정상",
      collateral: "부동산 담보",
      rm: "김민수",
      ratingChange: "유지",
    },
    {
      name: "현대자동차",
      rating: "AA+",
      loanAmount: 3500,
      interestRate: 3.5,
      delinquency: "정상",
      collateral: "부동산 담보",
      rm: "이지연",
      ratingChange: "상승",
    },
    {
      name: "SK하이닉스",
      rating: "AA",
      loanAmount: 2800,
      interestRate: 3.8,
      delinquency: "주의",
      collateral: "주식 담보",
      rm: "박철수",
      ratingChange: "하락",
    },
    {
      name: "LG에너지솔루션",
      rating: "AA",
      loanAmount: 4200,
      interestRate: 3.6,
      delinquency: "정상",
      collateral: "부동산 담보",
      rm: "최영희",
      ratingChange: "유지",
    },
    {
      name: "네이버",
      rating: "AA-",
      loanAmount: 1500,
      interestRate: 4.0,
      delinquency: "정상",
      collateral: "무담보",
      rm: "정수진",
      ratingChange: "유지",
    },
    {
      name: "카카오",
      rating: "A+",
      loanAmount: 1200,
      interestRate: 4.5,
      delinquency: "연체",
      collateral: "무담보",
      rm: "강동욱",
      ratingChange: "하락",
    },
    {
      name: "포스코",
      rating: "AA",
      loanAmount: 3800,
      interestRate: 3.7,
      delinquency: "정상",
      collateral: "부동산 담보",
      rm: "김민수",
      ratingChange: "유지",
    },
    {
      name: "LG전자",
      rating: "AA-",
      loanAmount: 2100,
      interestRate: 3.9,
      delinquency: "주의",
      collateral: "주식 담보",
      rm: "이지연",
      ratingChange: "하락",
    },
  ]);

  // ======== 🔧 수정: 실시간 등급 변동 감지 (폴링) ========
  const prevGradesRef = useRef<Record<string, string>>({});

  useEffect(() => {
    // 로그인 상태가 아니면 폴링 중지
    if (!isLoggedIn) return;

    const fetchGrades = async () => {
      try {
        const { data } = await axios.post(`${API_BASE}/analyze_many`, { companies: WATCHLIST });
        const results = data?.results || [];
        return results;
      } catch (e) {
        console.error("[App.tsx] /analyze_many 호출 실패:", e);
        return [];
      }
    };

    // 1. 초기 1회: 기준 등급 세팅
    const initializeGrades = async () => {
      const initResults = await fetchGrades();
      initResults.forEach((r: any) => {
        if (r.company && r.predicted_grade) {
          prevGradesRef.current[r.company] = r.predicted_grade;
        }
      });
      console.log("[App.tsx] Polling-base grades initialized:", prevGradesRef.current);
    };

    initializeGrades();

    // 2. 3분마다 폴링 시작
    const timer = setInterval(async () => {
      const latestResults = await fetchGrades();
      const newNotifications: Notification[] = [];

      latestResults.forEach((r: any) => {
        const company = r?.company;
        const next = r?.predicted_grade as string | undefined;
        if (!company || !next) return;

        const prev = prevGradesRef.current[company];

        // [핵심] 이전 등급이 있고, 등급이 변동된 경우
        if (prev && prev !== next) {
          const direction = getRatingOrder(next) < getRatingOrder(prev) ? "up" : "down";
          const newNotifId = Date.now() + Math.floor(Math.random() * 1000);
          
          const newNotif: Notification = {
            id: newNotifId,
            type: direction,
            companyName: company,
            title: `${company} 신용등급 ${direction === "up" ? "상승" : "하락"}`,
            ratingChange: `${prev} → ${next}`,
            newsKeywords: "실시간 등급 변동 감지",
            timestamp: new Date().toLocaleString("ko-KR"),
            isRead: false,
          };
          
          newNotifications.push(newNotif);

          // 1. Toast 팝업 띄우기
          const toastAction = {
            label: "상세보기",
            onClick: () => handleSelectNotification(newNotifId),
          };
          
          if (direction === "down") {
            toast.error(`🔴 [등급 하락] ${company} 등급이 ${next}로 하향되었습니다.`, {
              duration: 8000, action: toastAction, style: { border: "1px solid #dc2626", backgroundColor: "#fee2e2", color: "#7f1d1d", cursor: "pointer" },
              onClick: () => handleSelectNotification(newNotifId),
            });
          } else {
             toast.success(`🟢 [등급 상승] ${company} 등급이 ${next}로 상향되었습니다.`, {
              duration: 8000, action: toastAction, style: { border: "1px solid #16a34a", backgroundColor: "#dcfce7", color: "#14532d", cursor: "pointer" },
              onClick: () => handleSelectNotification(newNotifId),
            });
          }
        }
        
        // 3. 최신 등급으로 캐시 갱신
        prevGradesRef.current[company] = next;
      });

      // 2. 알림 상태 업데이트 (새 알림을 맨 위에 추가)
      if (newNotifications.length > 0) {
        setNotifications((prev) => [...newNotifications, ...prev].sort((a, b) => b.id - a.id));
      }

    }, POLL_MS);

    // 컴포넌트 언마운트 시 타이머 제거
    return () => clearInterval(timer);

  }, [isLoggedIn]); // ❗️ [수정] 기존 시뮬레이션 로직 전체 삭제, isLoggedIn 의존성으로 변경
  // ======================================================


  const handleLogin = () => {
    setIsLoggedIn(true);
    setCurrentScreen("dashboard");
  };

  const navigateToScreen = (screen: Screen) => {
    setScreenHistory((prev) => [...prev, currentScreen]);
    setCurrentScreen(screen);
  };

  const handleSearchCompany = (companyName: string) => {
    setSelectedCompany(companyName);
    navigateToScreen("company");
  };

  const handleViewMyList = () => {
    navigateToScreen("mylist");
  };

  const handleViewNotifications = () => {
    navigateToScreen("inbox");
  };

  // ❗️ [수정] 이 함수가 클릭 시 호출되도록 통일
  const handleSelectNotification = (id: number) => {
    setSelectedNotificationId(id);
    // 알림 목록에서 '읽음' 처리
    setNotifications((prev) =>
      prev.map((n) =>
        n.id === id ? { ...n, isRead: true } : n,
      ),
    );
    // 상세 화면으로 이동
    navigateToScreen("notification");
  };

  const handleSelectCompany = (companyName: string) => {
    setSelectedCompany(companyName);
    navigateToScreen("company");
  };

  const handleBackToDashboard = () => {
    setScreenHistory([]);
    setCurrentScreen("dashboard");
  };

  const handleGoBack = () => {
    if (screenHistory.length > 0) {
      const previousScreen = screenHistory[screenHistory.length - 1];
      setScreenHistory((prev) => prev.slice(0, -1));
      setCurrentScreen(previousScreen);
    } else {
      setCurrentScreen("dashboard");
    }
  };

  const handleViewAnalysis = () => {
    navigateToScreen("analysis");
  };

  // ❗️ [제거] 불필요
  // const handleViewNotificationDetail = () => {
  //   navigateToScreen("notification");
  // };

  const handleAddToMyCompanies = (companyName: string) => {
    const isAlreadyAdded = myCompanies.some(
      (company) => company.name === companyName
    );

    if (!isAlreadyAdded) {
      const newCompany: Company = {
        name: companyName,
        rating: "A+",
        loanAmount: 0,
        interestRate: 0,
        delinquency: "정상",
        collateral: "미정",
        rm: "미배정",
        ratingChange: "유지",
      };
      setMyCompanies([...myCompanies, newCompany]);
      toast.success(`${companyName}이(가) 관심기업 목록에 추가되었습니다.`);
    } else {
      toast.info(`${companyName}은(는) 이미 관심기업 목록에 있습니다.`);
    }
  };

  // '읽지 않음' 개수 계산 (정상)
  const unreadCount = notifications.filter(
    (n) => !n.isRead,
  ).length;
  
  // ❗️ [수정] 클릭한 알림 객체 찾기
  const selectedNotification = notifications.find(
    (n) => n.id === selectedNotificationId
  );

  return (
    <>
      <Toaster
        position="bottom-right"
        richColors
        closeButton
        toastOptions={{
          style: {
            cursor: "pointer",
          },
        }}
      />

      {currentScreen === "login" && (
        <LoginPage onLogin={handleLogin} />
      )}

      {currentScreen === "dashboard" && (
        <MainDashboard
          onSearchCompany={handleSearchCompany}
          onViewMyList={handleViewMyList}
          onViewNotifications={handleViewNotifications}
          unreadCount={unreadCount} // ❗️ App이 계산한 unreadCount 전달
          onAddToMyCompanies={handleAddToMyCompanies}
          myCompanies={myCompanies}
        />
      )}

      {currentScreen === "company" && (
        <CompanyAnalysis
          companyName={selectedCompany}
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
          // ❗️ 'onViewNotificationDetail' prop 제거
        />
      )}

      {currentScreen === "mylist" && (
        <MyCompaniesList
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
          onSelectCompany={handleSelectCompany}
          companies={myCompanies}
        />
      )}

      {currentScreen === "notification" && (
        <NotificationDetail
          // ❗️ [수정] 클릭한 알림 객체 전체를 전달
          notification={selectedNotification} 
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
          onViewAnalysis={handleViewAnalysis} // 이 prop은 NotificationDetail 파일 내에서 사용 안 함
        />
      )}

      {currentScreen === "analysis" && (
        <DeepAnalysisDashboard 
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
        />
      )}

      {currentScreen === "inbox" && (
        <NotificationInbox
          notifications={notifications} // ❗️ App이 관리하는 전체 알림 전달
          onBack={handleGoBack}
          onHome={handleBackToDashboard}
          onSelectNotification={handleSelectNotification} // ❗️ App의 상태 변경 함수 전달
        />
      )}
    </>
  );
}