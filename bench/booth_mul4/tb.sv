`timescale 1ns/1ps
// 自检测试台：256 种输入穷举；另外检查 RTL 里没有乘法运算符（由 meta.json 的 forbid 规则负责）。
module tb_booth_mul4;
    reg signed [3:0] m = 4'bx, q = 4'bx;
    // 输入先是 x：0 时刻第一组激励一定是一次变化，always @* 写的组合逻辑会被触发（SystemVerilog 里声明时的初值不产生事件）。
    wire signed [7:0] p;
    booth_mul4 dut(.m(m), .q(q), .p(p));
    integer a, b, errors = 0;
    initial begin
        for (a = -8; a <= 7; a = a + 1) for (b = -8; b <= 7; b = b + 1) begin
            m = a; q = b; #1;
            if (p !== a * b) begin
                errors = errors + 1;
                if (errors < 10) $display("TB_FAIL m=%0d q=%0d expected %0d got %0d", a, b, a * b, p);
            end
        end
        if (errors == 0) $display("TB_PASS booth_mul4: 256/256 products");
        else $display("TB_FAIL booth_mul4: %0d wrong products", errors);
        $finish;
    end
endmodule
