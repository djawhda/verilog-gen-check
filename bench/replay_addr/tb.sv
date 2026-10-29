`timescale 1ns/1ps
// 自检测试台：小参数（N=12，分频 2..9），逐周期比对参考模型；中途多次换槽位。
module tb_replay_addr;
    reg clk = 0; always #5 clk = ~clk;
    reg rst = 1;
    reg [2:0] slot = 3'bx;
    // 输入先是 x，1 ns 后再给初值：这样 0 时刻之后一定有一次输入变化，always @* 写的组合逻辑会被触发。
    // （SystemVerilog 里声明时的初值不产生事件；如果第一组激励恰好等于初值，always @* 一次都不执行，输出一直是 x。）
    initial #1 begin slot = 3'd2; end
    wire [14:0] addr; wire tick, sync;
    replay_addr #(.N(12), .DIV0(2), .DIV1(3), .DIV2(5), .DIV3(9),
                  .DIV4(4), .DIV5(7), .DIV6(6), .DIV7(8)) dut(
        .clk(clk), .rst(rst), .slot(slot), .addr(addr), .tick(tick), .sync(sync));

    // 参考模型
    reg [2:0] m_slot; integer m_cnt, m_idx; reg [14:0] m_addr; reg m_tick, m_sync;
    integer errors = 0, cycles = 0, ticks = 0, syncs = 0, k;

    function integer divof(input [2:0] s);
        case (s) 0: divof = 2; 1: divof = 3; 2: divof = 5; 3: divof = 9;
                 4: divof = 4; 5: divof = 7; 6: divof = 6; default: divof = 8; endcase
    endfunction

    always @(posedge clk) begin
        if (rst || slot != m_slot) begin
            m_slot <= slot; m_cnt <= 0; m_idx <= 0; m_addr <= {slot, 12'd0}; m_tick <= 0; m_sync <= 0;
        end else if (m_cnt == divof(m_slot) - 1) begin
            m_cnt <= 0;
            m_idx <= (m_idx == 11) ? 0 : m_idx + 1;
            m_addr <= {m_slot, 12'((m_idx == 11) ? 0 : m_idx + 1)};
            m_tick <= 1; m_sync <= (m_idx == 11);
        end else begin
            m_cnt <= m_cnt + 1; m_tick <= 0; m_sync <= 0;
        end
    end

    always @(negedge clk) if (!rst) begin
        cycles = cycles + 1;
        if (tick) ticks = ticks + 1;
        if (sync) syncs = syncs + 1;
        if (addr !== m_addr || tick !== m_tick || sync !== m_sync) begin
            errors = errors + 1;
            if (errors < 10)
                $display("TB_FAIL t=%0t slot=%0d expected addr=%h tick=%b sync=%b got addr=%h tick=%b sync=%b",
                         $time, m_slot, m_addr, m_tick, m_sync, addr, tick, sync);
        end
    end

    initial begin
        repeat (2) @(posedge clk);
        @(negedge clk); rst = 0;
        repeat (400) @(posedge clk);
        for (k = 0; k < 12; k = k + 1) begin
            @(negedge clk); slot = $random;
            repeat (37 + 23 * k) @(posedge clk);
        end
        @(negedge clk); rst = 1; @(negedge clk); rst = 0;
        repeat (300) @(posedge clk);
        @(negedge clk);
        if (syncs == 0 || ticks < 50) begin
            errors = errors + 1; $display("TB_FAIL too few ticks (%0d) or syncs (%0d)", ticks, syncs);
        end
        if (errors == 0) $display("TB_PASS replay_addr: %0d cycles, %0d ticks, %0d syncs", cycles, ticks, syncs);
        else $display("TB_FAIL replay_addr: %0d mismatching cycles", errors);
        $finish;
    end
endmodule
