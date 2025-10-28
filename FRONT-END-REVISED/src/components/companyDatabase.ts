// 전체 기업 데이터베이스
export interface CompanyData {
  name: string;
  rating: string;
  industry: string;
  description: string;
}

export const allCompanies: CompanyData[] = [
  {
    name: "삼성전자",
    rating: "AAA",
    industry: "전자/반도체",
    description: "글로벌 전자 및 반도체 제조업체",
  },
  {
    name: "삼성물산",
    rating: "AA+",
    industry: "건설/무역",
    description: "종합 건설 및 상사",
  },
  {
    name: "삼성생명",
    rating: "AA",
    industry: "보험",
    description: "생명보험 및 금융서비스",
  },
  {
    name: "삼성화재",
    rating: "AA",
    industry: "보험",
    description: "손해보험 및 금융서비스",
  },
  {
    name: "삼성SDI",
    rating: "AA-",
    industry: "배터리/소재",
    description: "이차전지 및 전자재료",
  },
  {
    name: "삼성중공업",
    rating: "A+",
    industry: "조선",
    description: "조선 및 해양플랜트",
  },
  {
    name: "삼성엔지니어링",
    rating: "A+",
    industry: "건설/엔지니어링",
    description: "플랜트 엔지니어링",
  },
  {
    name: "현대자동차",
    rating: "AA+",
    industry: "자동차",
    description: "자동차 제조 및 판매",
  },
  {
    name: "현대모비스",
    rating: "AA",
    industry: "자동차부품",
    description: "자동차 부품 제조",
  },
  {
    name: "현대건설",
    rating: "AA-",
    industry: "건설",
    description: "종합 건설업",
  },
  {
    name: "현대제철",
    rating: "AA-",
    industry: "철강",
    description: "철강 제조",
  },
  {
    name: "현대중공업",
    rating: "A+",
    industry: "조선",
    description: "조선 및 중공업",
  },
  {
    name: "SK하이닉스",
    rating: "AA",
    industry: "반도체",
    description: "메모리 반도체 제조",
  },
  {
    name: "SK텔레콤",
    rating: "AA",
    industry: "통신",
    description: "이동통신 서비스",
  },
  {
    name: "SK이노베이션",
    rating: "AA-",
    industry: "에너지/화학",
    description: "석유화학 및 배터리",
  },
  {
    name: "SK네트웍스",
    rating: "A+",
    industry: "유통/서비스",
    description: "종합 유통 및 서비스",
  },
  {
    name: "LG전자",
    rating: "AA-",
    industry: "전자/가전",
    description: "가전 및 전자제품 제조",
  },
  {
    name: "LG화학",
    rating: "AA",
    industry: "화학",
    description: "석유화학 및 소재",
  },
  {
    name: "LG에너지솔루션",
    rating: "AA",
    industry: "배터리",
    description: "이차전지 제조",
  },
  {
    name: "LG디스플레이",
    rating: "A+",
    industry: "디스플레이",
    description: "디스플레이 패널 제조",
  },
  {
    name: "LG유플러스",
    rating: "AA-",
    industry: "통신",
    description: "이동통신 서비스",
  },
  {
    name: "포스코",
    rating: "AA",
    industry: "철강",
    description: "철강 제조",
  },
  {
    name: "포스코케미칼",
    rating: "A+",
    industry: "화학/소재",
    description: "이차전지 소재",
  },
  {
    name: "네이버",
    rating: "AA-",
    industry: "IT/인터넷",
    description: "인터넷 포털 및 서비스",
  },
  {
    name: "카카오",
    rating: "A+",
    industry: "IT/인터넷",
    description: "모바일 플랫폼 및 콘텐츠",
  },
  {
    name: "카카오뱅크",
    rating: "A",
    industry: "금융",
    description: "인터넷전문은행",
  },
  {
    name: "신한은행",
    rating: "AA+",
    industry: "금융",
    description: "시중은행",
  },
  {
    name: "KB국민은행",
    rating: "AA+",
    industry: "금융",
    description: "시중은행",
  },
  {
    name: "하나은행",
    rating: "AA+",
    industry: "금융",
    description: "시중은행",
  },
  {
    name: "우리은행",
    rating: "AA",
    industry: "금융",
    description: "시중은행",
  },
  {
    name: "기아",
    rating: "AA",
    industry: "자동차",
    description: "자동차 제조",
  },
  {
    name: "한화",
    rating: "A+",
    industry: "화학/방산",
    description: "종합 화학 및 방산",
  },
  {
    name: "롯데쇼핑",
    rating: "A+",
    industry: "유통",
    description: "백화점 및 할인점",
  },
  {
    name: "롯데케미칼",
    rating: "A+",
    industry: "화학",
    description: "석유화학",
  },
  {
    name: "GS칼텍스",
    rating: "AA-",
    industry: "에너지",
    description: "정유 및 석유화학",
  },
  {
    name: "쿠팡",
    rating: "A",
    industry: "이커머스",
    description: "온라인 쇼핑 플랫폼",
  },
  {
    name: "CJ제일제당",
    rating: "AA-",
    industry: "식품",
    description: "식품 제조",
  },
  {
    name: "CJ대한통운",
    rating: "A+",
    industry: "물류",
    description: "종합 물류",
  },
];
