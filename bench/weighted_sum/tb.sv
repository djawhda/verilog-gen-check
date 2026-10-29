`timescale 1ns/1ps
// 自检测试台：每周期换输入，逐周期检查两级输出的延迟和舍入；含 Booth 实际取值和随机值。
module tb_weighted_sum;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1;
    reg signed [31:0] pp0 = 32'bx, pp1 = 32'bx;
    // 输入先是 x，1 ns 后再给初值：这样 0 时刻之后一定有一次输入变化，always @* 写的组合逻辑会被触发。
    // （SystemVerilog 里声明时的初值不产生事件；如果第一组激励恰好等于初值，always @* 一次都不执行，输出一直是 x。）
    initial #1 begin pp0 = 0; pp1 = 0; end
    wire signed [31:0] unscaled, inv, prod;
    weighted_sum dut(.clk(clk), .rst(rst), .pp0_q20(pp0), .pp1_q20(pp1),
                     .unscaled_q20(unscaled), .inverting_sum_q20(inv), .product_q20(prod));
    reg signed [63:0] hist [0:8191];
    integer n = 0, errors = 0, k, m, d0, d1, checked = 0;
    reg signed [63:0] u;

    function automatic signed [63:0] rnd(input signed [63:0] uu);
        reg signed [63:0] num, mag;
        begin
            num = 9 * uu;
            mag = (num < 0 ? -num : num) + 10;
            mag = mag / 20;
            rnd = (num < 0) ? -mag : mag;
        end
    endfunction

    // 每个上升沿记下此刻被采样的 u
    always @(posedge clk) if (!rst) begin
        hist[n] = pp0 + 4 * pp1;
        n = n + 1;
    end
    // 输入在下降沿改变；检查放在上升沿之后 2 ns（寄存器已更新、输入还没变）
    always @(posedge clk) if (!rst) begin
        #2;
        if (unscaled !== pp0 + 4 * pp1) begin
            errors = errors + 1; if (errors < 10) $display("TB_FAIL unscaled: expected %0d got %0d", pp0 + 4 * pp1, unscaled);
        end
        if (n >= 4) begin
            checked = checked + 1;
            if (inv !== -rnd(hist[n - 4]) || (n >= 5 && prod !== rnd(hist[n - 5]))) begin
                errors = errors + 1;
                if (errors < 10) $display("TB_FAIL edge %0d: u(inv)=%0d expected inverting=%0d got %0d; u(prod)=%0d expected product=%0d got %0d",
                    n, hist[n - 4], -rnd(hist[n - 4]), inv, (n >= 5 ? hist[n - 5] : 0), (n >= 5 ? rnd(hist[n - 5]) : 0), prod);
            end
        end
    end

    initial begin
        repeat (3) @(posedge clk); #1;
        if (inv !== 0 || prod !== 0) begin errors = errors + 1; $display("TB_FAIL reset: outputs not zero"); end
        @(negedge clk); rst = 0;
        // Booth 实际取值：M=-8..7，数字 -2..2
        for (m = -8; m <= 7; m = m + 1) for (d0 = -2; d0 <= 2; d0 = d0 + 1) for (d1 = -2; d1 <= 2; d1 = d1 + 1) begin
            @(negedge clk); pp0 = m * d0 * 65536; pp1 = m * d1 * 65536;
        end
        // 舍入边界和随机值
        for (k = -40; k <= 40; k = k + 1) begin @(negedge clk); pp0 = k; pp1 = 0; end
        for (k = 0; k < 3000; k = k + 1) begin
            @(negedge clk); pp0 = $random % 6000000; pp1 = $random % 2000000;
        end
        @(negedge clk); pp0 = 0; pp1 = 0;
        repeat (8) @(posedge clk);
        @(negedge clk);
        if (errors == 0) $display("TB_PASS weighted_sum: %0d cycles checked", checked);
        else $display("TB_FAIL weighted_sum: %0d errors", errors);
        $finish;
    end
endmodule
