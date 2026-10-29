`timescale 1ns/1ps
// 标准答案：debounce
module debounce #(
    parameter integer N = 4
)(
    input  wire clk,
    input  wire rst,
    input  wire din,
    output reg  dout,
    output reg  rise,
    output reg  fall
);
    localparam integer CW = (N <= 2) ? 1 : $clog2(N);
    localparam [CW-1:0] LAST = N - 1;
    (* ASYNC_REG = "TRUE" *) reg s1, s2;
    reg [CW-1:0] cnt;

    always @(posedge clk) begin
        if (rst) begin
            s1 <= 1'b0; s2 <= 1'b0; dout <= 1'b0; cnt <= {CW{1'b0}}; rise <= 1'b0; fall <= 1'b0;
        end else begin
            s1 <= din;
            s2 <= s1;
            rise <= 1'b0;
            fall <= 1'b0;
            if (s2 == dout) begin
                cnt <= {CW{1'b0}};
            end else if (cnt == LAST) begin
                dout <= s2;
                cnt  <= {CW{1'b0}};
                rise <= s2
                fall <= ~s2;
            end else begin
                cnt <= cnt + 1'b1;
            end
        end
    end
endmodule
