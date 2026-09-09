import { ArrowLeft, Home, TrendingDown, TrendingUp, Minus, AlertCircle } from "lucide-react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./ui/table";
import { Badge } from "./ui/badge";
import kiwoomLogo from "figma:asset/7edd7880e1ed1575f3f3496ccc95c4ca1ab02475.png";

interface Company {
  name: string;
  rating: string;
  loanAmount: number;
  interestRate: number;
  delinquency: string;
  collateral: string;
  rm: string;
  ratingChange: string;
}

interface MyCompaniesListProps {
  onBack: () => void;
  onHome: () => void;
  onSelectCompany: (companyName: string) => void;
  companies: Company[];
}

export function MyCompaniesList({
  onBack,
  onHome,
  onSelectCompany,
  companies,
}: MyCompaniesListProps) {
  const getRatingChangeIcon = (change: string) => {
    switch (change) {
      case "상승":
        return <TrendingUp className="w-4 h-4" />;
      case "하락":
        return <TrendingDown className="w-4 h-4" />;
      default:
        return <Minus className="w-4 h-4" />;
    }
  };

  const getRatingChangeBadge = (change: string) => {
    switch (change) {
      case "상승":
        return (
          <Badge className="bg-green-50 text-green-700 border-green-200 hover:bg-green-50">
            <TrendingUp className="w-3 h-3 mr-1" />
            등급 상승
          </Badge>
        );
      case "하락":
        return (
          <Badge className="bg-red-50 text-red-700 border-red-200 hover:bg-red-50">
            <TrendingDown className="w-3 h-3 mr-1" />
            등급 하락
          </Badge>
        );
      default:
        return (
          <Badge
            variant="outline"
            className="bg-[var(--card)] text-[var(--muted-foreground)] border-[#AD1765]"
          >
            <Minus className="w-3 h-3 mr-1" />
            등급 유지
          </Badge>
        );
    }
  };

  const getDelinquencyBadge = (status: string) => {
    switch (status) {
      case "정상":
        return (
          <Badge className="bg-green-50 text-green-700 border-green-200 hover:bg-green-50">
            정상
          </Badge>
        );
      case "주의":
        return (
          <Badge className="bg-yellow-50 text-yellow-700 border-yellow-200 hover:bg-yellow-50">
            <AlertCircle className="w-3 h-3 mr-1" />
            주의
          </Badge>
        );
      case "연체":
        return (
          <Badge className="bg-red-50 text-red-700 border-red-200 hover:bg-red-50">
            <AlertCircle className="w-3 h-3 mr-1" />
            연체
          </Badge>
        );
      default:
        return (
          <Badge
            variant="outline"
            className="bg-[var(--card)] text-[var(--muted-foreground)] border-[#AD1765]"
          >
            {status}
          </Badge>
        );
    }
  };

  return (
    <div className="min-h-screen bg-[var(--background)]">
      {/* Header */}
      <header className="bg-[var(--card)] border-b border-[#AD1765] shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            {/* Kiwoom Logo */}
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 flex items-center justify-center">
                <img src={kiwoomLogo} alt="Kiwoom Logo" className="w-full h-full object-contain" />
              </div>
              <span className="text-[var(--foreground)]">키움은행</span>
            </div>
            {/* Divider */}
            <div className="h-8 w-px bg-[var(--border)]/70"></div>
            {/* ACI Logo */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#AD1765] to-[#8B1252] flex items-center justify-center">
                <span className="text-white tracking-tight">ACI</span>
              </div>
              <span className="text-[var(--foreground)]">AI Credit Insight</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={onHome} variant="ghost" className="text-[var(--muted-foreground)] hover:bg-[var(--primary)]/10">
              <Home className="w-4 h-4 mr-2" />
              처음으로
            </Button>
            <Button onClick={onBack} variant="ghost" className="text-[var(--muted-foreground)] hover:bg-[var(--primary)]/10">
              <ArrowLeft className="w-4 h-4 mr-2" />
              돌아가기
            </Button>
          </div>
        </div>
      </header>

      {/* Content */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h1 className="text-[var(--foreground)] mb-2">관리 기업 목록</h1>
          <p className="text-[var(--muted-foreground)]">
            담당 중인 기업의 대출 현황과 신용등급 변동을 한눈에 확인하세요
          </p>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <Card className="p-4 bg-[var(--card)] border border-[var(--border)]">
            <div className="text-[var(--muted-foreground)] mb-1">총 관리 기업</div>
            <div className="text-[var(--foreground)]">{companies.length}개</div>
          </Card>
          <Card className="p-4 bg-[var(--card)] border border-[var(--border)]">
            <div className="text-[var(--muted-foreground)] mb-1">총 대출금액</div>
            <div className="text-[var(--foreground)]">
              {companies.reduce((sum, c) => sum + c.loanAmount, 0).toLocaleString()}억 원
            </div>
          </Card>
          <Card className="p-4 bg-[var(--card)] border border-[var(--border)]">
            <div className="text-[var(--muted-foreground)] mb-1">연체/주의 기업</div>
            <div className="text-red-600">
              {companies.filter(c => c.delinquency === "연체" || c.delinquency === "주의").length}개
            </div>
          </Card>
          <Card className="p-4 bg-[var(--card)] border border-[var(--border)]">
            <div className="text-[var(--muted-foreground)] mb-1">등급 하락</div>
            <div className="text-orange-600">
              {companies.filter(c => c.ratingChange === "하락").length}개
            </div>
          </Card>
        </div>

        <Card className="bg-[var(--card)] border border-[var(--border)]">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-[var(--muted-foreground)]">기업명</TableHead>
                  <TableHead className="text-[var(--muted-foreground)]">신용등급</TableHead>
                  <TableHead className="text-right text-[var(--muted-foreground)]">대출금액</TableHead>
                  <TableHead className="text-right text-[var(--muted-foreground)]">금리</TableHead>
                  <TableHead className="text-[var(--muted-foreground)]">연체 현황</TableHead>
                  <TableHead className="text-[var(--muted-foreground)]">담보물</TableHead>
                  <TableHead className="text-[var(--muted-foreground)]">담당 RM</TableHead>
                  <TableHead className="text-[var(--muted-foreground)]">등급 변동</TableHead>
                  <TableHead className="text-right text-[var(--muted-foreground)]">작업</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {companies.map((company) => (
                  <TableRow
                    key={company.name}
                    className="cursor-pointer hover:bg-[var(--accent)]/10"
                    onClick={() => onSelectCompany(company.name)}
                  >
                    <TableCell>
                      <span className="text-[var(--foreground)]">{company.name}</span>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className="bg-[var(--primary)]/10 text-[var(--primary)] border-[var(--primary)]/20"
                      >
                        {company.rating}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <span className="text-[var(--foreground)]">
                        {company.loanAmount > 0 ? `${company.loanAmount.toLocaleString()}억` : '-'}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <span className="text-[var(--foreground)]">{company.interestRate > 0 ? `${company.interestRate}%` : '-'}</span>
                    </TableCell>
                    <TableCell>{getDelinquencyBadge(company.delinquency)}</TableCell>
                    <TableCell>
                      <span className="text-[var(--muted-foreground)]">{company.collateral}</span>
                    </TableCell>
                    <TableCell>
                      <span className="text-[var(--muted-foreground)]">{company.rm}</span>
                    </TableCell>
                    <TableCell>
                      {getRatingChangeBadge(company.ratingChange)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectCompany(company.name);
                        }}
                        className="text-[var(--primary)] hover:bg-[var(--primary)]/10"
                      >
                        상세 보기
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
      </div>
    </div>
  );
}
