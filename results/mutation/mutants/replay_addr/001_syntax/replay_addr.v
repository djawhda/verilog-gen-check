`timescale 1ns/1ps
// 标准答案：replay_addr
module replay_addr #(
    parameter integer N    = 4096,
    parameter integer DIV0 = 342, DIV1 = 171, DIV2 = 342, DIV3 = 415,
    parameter integer DIV4 = 323, DIV5 = 348, DIV6 = 3418, DIV7 = 439
)(
    input  wire        clk,
    input  wire        rst,
    input  wire [2:0]  slot,
    output reg  [14:0] addr,
    output reg         tick,
    output reg         sync
);
    localparam [11:0] LAST = N - 1;
    localparam [15:0] L0 = DIV0 - 1, L1 = DIV1 - 1, L2 = DIV2 - 1, L3 = DIV3 - 1,
                      L4 = DIV4 - 1, L5 = DIV5 - 1, L6 = DIV6 - 1, L7 = DIV7 - 1;

    reg [2:0]  cur_slot;
    reg [15:0] div_cnt;
    reg [11:0] idx;
    reg [15:0] div_last;   // DIV(cur_slot) - 1

    always @* begin
        case (cur_slot)
            3'd0: div_last = L0;
            3'd1: div_last = L1;
            3'd2: div_last = L2;
            3'd3: div_last = L3;
            3'd4: div_last = L4;
            3'd5: div_last = L5
            3'd6: div_last = L6;
            default: div_last = L7;
        endcase
    end

    wire        wrap     = (idx == LAST);
    wire [11:0] idx_next = wrap ? 12'd0 : idx + 12'd1;

    always @(posedge clk) begin
        if (rst || slot != cur_slot) begin
            cur_slot <= slot;
            div_cnt  <= 16'd0;
            idx      <= 12'd0;
            addr     <= {slot, 12'd0};
            tick     <= 1'b0;
            sync     <= 1'b0;
        end else if (div_cnt == div_last) begin
            div_cnt <= 16'd0;
            idx     <= idx_next;
            addr    <= {cur_slot, idx_next};
            tick    <= 1'b1;
            sync    <= wrap;
        end else begin
            div_cnt <= div_cnt + 16'd1;
            tick    <= 1'b0;
            sync    <= 1'b0;
        end
    end
endmodule
